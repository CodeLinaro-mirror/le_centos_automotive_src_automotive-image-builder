"""Unit tests for the reproducible-build defines injected by
``create_osbuild_manifest`` (SOURCE_DATE_EPOCH, manifest mtime, and the
manifest content hash used to derive a deterministic image UUID), and for
the mpp-side timestamp chain (explicit timestamp > SOURCE_DATE_EPOCH >
newest resolved RPM buildtime > manifest mtime > 1).

These tests do not run mpp or osbuild: they mock the heavy bits (the osbuild
version probe and the container runner) and assert on the ``-D key=value``
defines that get handed to the mpp command line. The timestamp-chain tests
evaluate the actual mpp-eval expressions from the include files, using the
real ``_Lazy``/``_materialize`` helpers loaded from main.ipp.yml.
"""

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import yaml

from aib import exceptions
from aib import osbuild

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _include_mpp_vars(name):
    with open(os.path.join(_REPO_ROOT, "include", name)) as f:
        return yaml.safe_load(f)["mpp-vars"]


def _mpp_helpers():
    """Eval the real _Lazy/_m/_materialize definitions from main.ipp.yml.

    They are evaluated into one shared env dict so that later definitions see
    the earlier ones, mirroring how mpp accumulates vars.
    """
    mv = _include_mpp_vars("main.ipp.yml")
    env = {}
    for k in ("_Lazy", "_m", "_materialize"):
        env[k] = eval(mv[k]["mpp-eval"], env)  # pylint: disable=eval-used
    return env


class _FakeTmpDir(os.PathLike):
    """Stand-in for the SudoTemporaryDirectory passed in production.

    ``create_osbuild_manifest`` uses the object both as ``tmpdir.name`` and via
    ``os.path.join(tmpdir, ...)``, so it must expose ``.name`` and be PathLike.
    """

    def __init__(self, path):
        self.name = path
        self._path = path

    def __fspath__(self):
        return self._path


class CreateManifestReproducibleTest(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup)
        # A minimal but valid manifest with mpp-vars (so the vars-split path runs).
        self.manifest_path = os.path.join(self.workdir, "test.aib.yml")
        with open(self.manifest_path, "w") as f:
            f.write(
                "version: '2'\n"
                "mpp-vars:\n  name: test\n"
                "pipelines:\n  - name: build\n"
            )
        self.out_path = os.path.join(self.workdir, "out.json")
        self.tmpdir = _FakeTmpDir(self.workdir)

    def _cleanup(self):
        import shutil

        shutil.rmtree(self.workdir, ignore_errors=True)

    def _args(self):
        return SimpleNamespace(
            manifest=self.manifest_path,
            base_dir="/base",
            arch="x86_64",
            distro="autosd10",
            mode="image",
            container=False,
            dump_variables=False,
            policy=None,
            simple_manifest=None,
            target="qemu",
            ostree_repo=None,
            define=[],
            define_file=[],
            extend_define=[],
            local_repo=None,
            include_dirs=[],
            cache=None,
        )

    def _run(self, args=None, env=None):
        """Run create_osbuild_manifest and return the parsed defines dict.

        Parses the ``-D key=<json>`` pairs back out of the captured mpp cmdline.
        """
        args = args or self._args()
        runner = Mock()
        with patch.dict(os.environ, env or {}, clear=False):
            if env is not None and "SOURCE_DATE_EPOCH" not in env:
                os.environ.pop("SOURCE_DATE_EPOCH", None)
            with patch("aib.osbuild.get_osbuild_major_version", return_value=2):
                osbuild.create_osbuild_manifest(
                    args, self.tmpdir, self.out_path, runner, storage=None
                )
        runner.run_in_container.assert_called_once()
        cmdline = runner.run_in_container.call_args[0][0]
        defines = {}
        it = iter(cmdline)
        for tok in it:
            if tok == "-D":
                k, v = next(it).split("=", 1)
                defines[k] = json.loads(v)
        return defines

    def test_source_date_epoch_valid(self):
        defines = self._run(env={"SOURCE_DATE_EPOCH": "1700000000"})
        self.assertEqual(defines["source_date_epoch"], 1700000000)

    def test_source_date_epoch_absent(self):
        defines = self._run(env={})
        self.assertNotIn("source_date_epoch", defines)

    def test_source_date_epoch_invalid_raises(self):
        for bad in ("abc", "-5", "1.5"):
            with self.subTest(value=bad):
                with self.assertRaises(exceptions.AIBException):
                    self._run(env={"SOURCE_DATE_EPOCH": bad})

    def test_manifest_mtime_is_int(self):
        defines = self._run(env={})
        self.assertIsInstance(defines["manifest_mtime"], int)
        self.assertEqual(
            defines["manifest_mtime"], int(os.stat(self.manifest_path).st_mtime)
        )

    def test_content_hash_stable_for_identical_input(self):
        a = self._run(env={})["manifest_content_hash"]
        b = self._run(env={})["manifest_content_hash"]
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)  # sha256 hex digest

    def test_content_hash_changes_with_defines(self):
        base = self._run(env={})["manifest_content_hash"]
        args = self._args()
        args.define = ["foo=bar"]
        changed = self._run(args=args, env={})["manifest_content_hash"]
        self.assertNotEqual(base, changed)

    def test_content_hash_excludes_tmpdir_paths(self):
        # _workdir/_basedir are volatile and must not affect the hash.
        base = self._run(env={})["manifest_content_hash"]
        args = self._args()
        args.base_dir = "/some/other/base"
        other = self._run(args=args, env={})["manifest_content_hash"]
        self.assertEqual(base, other)

    def test_content_hash_changes_with_local_repo(self):
        # local_repo feeds the repo baseurls (changes package resolution), so it
        # must be part of the deterministic image identity.
        base = self._run(env={})["manifest_content_hash"]
        args = self._args()
        args.local_repo = "/some/local/repo"
        changed = self._run(args=args, env={})["manifest_content_hash"]
        self.assertNotEqual(base, changed)

    def test_content_hash_changes_with_policy(self):
        # Policy forces vars and denylists rpms/modules/sysctls/selinux, all of
        # which change the image, so it must be part of the deterministic identity.
        from aib.policy import Policy

        base = self._run(env={})["manifest_content_hash"]
        args = self._args()
        args.policy = Policy(
            {"name": "p", "restrictions": {"rpms": {"disallow": ["foo"]}}}, "qemu"
        )
        changed = self._run(args=args, env={})["manifest_content_hash"]
        self.assertNotEqual(base, changed)

    def test_content_hash_changes_with_policy_restrictions(self):
        # Two different policies must not collide on the same UUID.
        from aib.policy import Policy

        args = self._args()
        args.policy = Policy(
            {"name": "p", "restrictions": {"rpms": {"disallow": ["foo"]}}}, "qemu"
        )
        a = self._run(args=args, env={})["manifest_content_hash"]
        args2 = self._args()
        args2.policy = Policy(
            {"name": "p", "restrictions": {"rpms": {"disallow": ["bar"]}}}, "qemu"
        )
        b = self._run(args=args2, env={})["manifest_content_hash"]
        self.assertNotEqual(a, b)

    def test_content_hash_ignores_source_date_epoch(self):
        # SOURCE_DATE_EPOCH only affects the build timestamp (metadata), not the
        # image recipe, so it must NOT change the deterministic UUID.
        base = self._run(env={})["manifest_content_hash"]
        with_sde = self._run(env={"SOURCE_DATE_EPOCH": "1700000000"})[
            "manifest_content_hash"
        ]
        self.assertEqual(base, with_sde)


class BuildTimestampTimezoneTest(unittest.TestCase):
    """build_timestamp must render in UTC so the /etc/build-info string is the
    same regardless of the build host's timezone (cross-env reproducibility)."""

    def _eval_build_timestamp(self, ts, tz):
        import time

        expr = _include_mpp_vars("computed-vars.ipp.yml")["build_timestamp"]["mpp-eval"]
        old_tz = os.environ.get("TZ")
        try:
            os.environ["TZ"] = tz
            time.tzset()
            import datetime as _datetime

            env = {**_mpp_helpers(), "_datetime": _datetime, "timestamp": ts}
            # build_timestamp is _Lazy; resolve it like the embed site does.
            return env["_materialize"](eval(expr, env))  # pylint: disable=eval-used
        finally:
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()

    def test_build_timestamp_is_utc_and_tz_independent(self):
        utc = self._eval_build_timestamp(1700000000, "UTC")
        cet = self._eval_build_timestamp(1700000000, "Europe/Bratislava")
        self.assertEqual(utc, cet)
        self.assertEqual(utc, "2023-11-14 22:13:20 UTC")


class TimestampPrecedenceTest(unittest.TestCase):
    """Evaluate the ``timestamp`` mpp-eval from computed-vars.ipp.yml and
    verify the full fallback chain, including the lazily-resolved RPM
    buildtime branch."""

    @staticmethod
    def _pkg(buildtime):
        return SimpleNamespace(buildtime=buildtime)

    def _eval_timestamp(
        self,
        reproducible_image=True,
        source_date_epoch=None,
        manifest_mtime=1600000000,
        rpms=None,
        extra_env=None,
    ):
        """Return (resolved value, env) for the timestamp expression.

        The returned env lets tests mutate ``rpms`` between eval and
        materialize, mimicking how depsolve fills the dict after the var was
        evaluated.
        """
        import datetime as _datetime

        expr = _include_mpp_vars("computed-vars.ipp.yml")["timestamp"]["mpp-eval"]
        env = {
            **_mpp_helpers(),
            "_datetime": _datetime,
            "reproducible_image": reproducible_image,
            "source_date_epoch": source_date_epoch,
            "manifest_mtime": manifest_mtime,
            "rpms": {} if rpms is None else rpms,
        }
        env.update(extra_env or {})
        return eval(expr, env), env  # pylint: disable=eval-used

    def _materialized(self, **kwargs):
        value, env = self._eval_timestamp(**kwargs)
        return env["_materialize"](value)

    def test_rpm_buildtime_wins_over_mtime(self):
        ts = self._materialized(
            rpms={
                "rootfs": {"a": self._pkg(100), "b": self._pkg(300)},
                "qm_rootfs_base": {"c": self._pkg(200)},
            }
        )
        self.assertEqual(ts, 300)

    def test_build_pipeline_excluded(self):
        # The build container is not image content; its packages must not
        # influence the image timestamp.
        ts = self._materialized(
            rpms={
                "rootfs": {"a": self._pkg(300)},
                "build": {"x": self._pkg(9999)},
            }
        )
        self.assertEqual(ts, 300)

    def test_mtime_fallback_when_no_rpms(self):
        self.assertEqual(self._materialized(rpms={}), 1600000000)

    def test_mtime_fallback_when_buildtimes_missing(self):
        # Non-dnf solvers may not provide buildtime.
        ts = self._materialized(rpms={"rootfs": {"a": self._pkg(None)}})
        self.assertEqual(ts, 1600000000)

    def test_epoch_fallback_when_no_mtime_either(self):
        self.assertEqual(self._materialized(rpms={}, manifest_mtime=None), 1)

    def test_source_date_epoch_wins_over_buildtime(self):
        value, _ = self._eval_timestamp(
            source_date_epoch=1700000000,
            rpms={"rootfs": {"a": self._pkg(300)}},
        )
        # SDE short-circuits the lazy branch entirely: plain int, not Lazy.
        self.assertEqual(value, 1700000000)
        self.assertIsInstance(value, int)

    def test_non_reproducible_uses_now(self):
        import time

        value, _ = self._eval_timestamp(reproducible_image=False)
        self.assertAlmostEqual(value, time.time(), delta=60)

    def test_explicit_timestamp_overrides_everything(self):
        ts = self._materialized(
            source_date_epoch=1700000000,
            rpms={"rootfs": {"a": self._pkg(300)}},
            extra_env={"timestamp": 42},
        )
        self.assertEqual(ts, 42)

    def test_lazy_sees_rpms_resolved_after_eval(self):
        # The whole timing contract: timestamp is evaluated before any
        # depsolve, and rpms[] is filled in place afterwards. The Lazy must
        # pick up the late-arriving packages when materialized.
        value, env = self._eval_timestamp(rpms={})
        env["rpms"]["rootfs"] = {"a": self._pkg(1234)}
        self.assertEqual(env["_materialize"](value), 1234)


class BuildInfoLazyTest(unittest.TestCase):
    """The build_info var must defer its TIMESTAMP field until materialized
    (i.e. until after depsolve), while rendering all other fields."""

    def test_build_info_materializes_with_late_timestamp(self):
        import datetime as _datetime

        helpers = _mpp_helpers()
        cv = _include_mpp_vars("computed-vars.ipp.yml")
        env = {
            **helpers,
            "_datetime": _datetime,
            "reproducible_image": True,
            "source_date_epoch": None,
            "manifest_mtime": None,
            "rpms": {},
            "distro_name": "autosd10",
            "release_name": "rel",
            "image_uuid": "11111111-2222-3333-4444-555555555555",
            "name": "test",
            "image_mode": "image",
            "target": "qemu",
            "version": "1",
        }
        # Evaluate timestamp -> build_timestamp -> build_info in mpp order,
        # accumulating vars like mpp does, all before "depsolve".
        env["timestamp"] = eval(  # pylint: disable=eval-used
            cv["timestamp"]["mpp-eval"], env
        )
        env["build_timestamp"] = eval(  # pylint: disable=eval-used
            cv["build_timestamp"]["mpp-eval"], env
        )
        ct = _include_mpp_vars("content.ipp.yml")
        build_info = eval(  # pylint: disable=eval-used
            ct["build_info"]["mpp-eval"], env
        )

        # Depsolve happens "later": fill rpms, then materialize at the embed.
        env["rpms"]["rootfs"] = {"a": SimpleNamespace(buildtime=1700000000)}
        text = env["_materialize"](build_info)
        self.assertIn('TIMESTAMP="2023-11-14 22:13:20 UTC"', text)
        self.assertIn('DISTRO="autosd10"', text)
        self.assertIn('IMAGE_VERSION="1"', text)
        self.assertTrue(text.endswith('"\n'))


if __name__ == "__main__":
    unittest.main()
