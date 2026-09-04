import hashlib
import importlib.machinery
import importlib.util
import io
import pathlib
import sys
import types

import pytest


def stub_module(monkeypatch, name, **attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    if name in ("osbuild", "osbuild.solver"):
        module.__path__ = []
    monkeypatch.setitem(sys.modules, name, module)


@pytest.fixture
def mpp_module(monkeypatch):
    dummy = type("Dummy", (), {})
    stub_module(monkeypatch, "rpm", expandMacro=lambda _macro: "x86_64")
    stub_module(monkeypatch, "osbuild")
    stub_module(monkeypatch, "osbuild.solver")
    stub_module(monkeypatch, "osbuild.solver.dnf", DNF=dummy)
    stub_module(monkeypatch, "osbuild.solver.model", Repository=dummy)
    stub_module(
        monkeypatch,
        "osbuild.solver.request",
        SolverConfig=dummy,
        DepsolveCmdArgs=dummy,
        DepsolveTransaction=dummy,
    )

    repo_root = pathlib.Path(__file__).parents[2]
    path = repo_root / "mpp" / "aib-osbuild-mpp"
    monkeypatch.syspath_prepend(str(path.parent))
    loader = importlib.machinery.SourceFileLoader("aib_osbuild_mpp", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def new_manifest(mpp_module, lockfile_data=None, lockfile_output=None):
    manifest = mpp_module.ManifestFileV2.__new__(mpp_module.ManifestFileV2)
    manifest.lockfile_data = lockfile_data
    manifest.lockfile_output = lockfile_output
    manifest.sources = {}
    manifest.vars = {}
    manifest.overrides = {}
    manifest.format_stack = []
    manifest.path = pathlib.Path("test.mpp.yml")
    manifest.basedir = pathlib.Path(".")
    return manifest


def embedded_url_stage(url):
    return {
        "inputs": {
            "file": {
                "type": "org.osbuild.files",
                "origin": "org.osbuild.source",
                "mpp-embed": {"id": "remote-file", "url": url},
            }
        }
    }


def container_stage(index):
    return {
        "type": "org.osbuild.skopeo",
        "inputs": {
            "images": {
                "type": "org.osbuild.containers",
                "origin": "org.osbuild.source",
                "mpp-resolve-images": {
                    "images": [{"source": "example.com/image", "index": index}]
                },
            }
        },
    }


def ostree_stage(remote, ref, target=None):
    commit = {"remote": remote, "ref": ref}
    if target is not None:
        commit["target"] = target
    return {
        "type": "org.osbuild.ostree.pull",
        "inputs": {
            "commits": {
                "type": "org.osbuild.ostree",
                "origin": "org.osbuild.source",
                "mpp-resolve-ostree-commits": {"commits": [commit]},
            }
        },
    }


def test_embedded_url_lockfile_generation_and_replay(mpp_module, monkeypatch):
    url = "https://example.com/remote-file"
    content = b"locked content"
    checksum = hashlib.sha256(content).hexdigest()
    lockfile = {"version": 1}
    calls = []

    def urlopen(request_url):
        calls.append(request_url)
        return io.BytesIO(content)

    monkeypatch.setattr(mpp_module.urllib.request, "urlopen", urlopen)

    generated = new_manifest(mpp_module, lockfile_output=lockfile)
    generated._process_embed_files(embedded_url_stage(url))

    assert calls == [url]
    assert list(lockfile["embedded_files"].values()) == [{"checksum": checksum}]
    assert url not in str(lockfile)

    monkeypatch.setattr(
        mpp_module.urllib.request,
        "urlopen",
        lambda _url: pytest.fail("locked replay downloaded the embedded file"),
    )

    replayed = new_manifest(mpp_module, lockfile_data=lockfile)
    replayed._process_embed_files(embedded_url_stage(url))

    digest = f"sha256:{checksum}"
    assert replayed.sources["org.osbuild.curl"]["items"] == {digest: url}


def test_embedded_url_lockfile_miss(mpp_module, monkeypatch):
    monkeypatch.setattr(
        mpp_module.urllib.request,
        "urlopen",
        lambda _url: pytest.fail("lockfile miss downloaded the embedded file"),
    )

    manifest = new_manifest(mpp_module, lockfile_data={"version": 1})
    with pytest.raises(
        RuntimeError, match="Lockfile miss for embedded file remote-file"
    ):
        manifest._process_embed_files(
            embedded_url_stage("https://example.com/remote-file")
        )


def test_lock_request_sanitizes_fields_and_preserves_nested_urls(mpp_module):
    request = {
        "root-dir": "/host/root",
        "username": "user",
        "password": "secret",
        "sslclientkey": "/host/client.key",
        "sslclientcert": "/host/client.crt",
        "sslcacert": "/host/ca.crt",
        "optional": None,
        "repos": [
            {
                "baseurl": "file:///host/repo",
                "metalink": "https://user:password@example.com/metalink",
                "mirrorlist": "https://user:password@example.com/mirrors",
                "username": "repo-user",
                "password": "repo-secret",
                "sslclientkey": "/host/repo-client.key",
                "optional": None,
            }
        ],
        "remote": {
            "url": "https://user:password@example.com/repo",
            "contenturl": "file:///host/content",
        },
    }

    assert mpp_module.ManifestFile._lock_sanitize_request(request) == {
        "repos": [
            {
                "baseurl": "file:///host/repo",
                "metalink": "https://user:password@example.com/metalink",
                "mirrorlist": "https://user:password@example.com/mirrors",
            }
        ],
        "remote": {
            "url": "https://user:password@example.com/repo",
            "contenturl": "file:///host/content",
        },
    }


@pytest.mark.parametrize(
    "lockfile",
    [
        {"url": "https://user:secret@example.com/package.rpm"},
        {"password": "secret"},
        {"url": "https://example.com/package.rpm?password=secret"},
    ],
)
def test_lockfile_warns_about_passwords(mpp_module, capsys, lockfile):
    mpp_module.ManifestFile._lock_warn_passwords(lockfile, "output.lock")

    captured = capsys.readouterr()
    assert "WARNING: lockfile 'output.lock' contains embedded passwords" in captured.err
    assert "secret" not in captured.err


def test_depsolve_lock_uses_releasever_from_root_dir(mpp_module, tmp_path):
    class Solver:
        def reset(
            self,
            _arch,
            _basedir,
            _module_platform_id,
            _ignore_weak_deps,
            releasever=None,
            root_dir=None,
        ):
            self.releasever = releasever

        def add_repo(self, _repo, _baseurl):
            pass

        def resolve(self, _packages, _excludes, enabled_repo_ids=None):
            package = mpp_module.PkgInfo(
                "sha256:package",
                "package",
                "1-1",
                "x86_64",
                license_tag="MIT",
            )
            package.url = "https://example.com/package.rpm"
            return [package]

    class SolverFactory:
        def __init__(self, solver):
            self.solver = solver

        def get_depsolver(self, _name):
            return self.solver

    def make_root(name, releasever):
        root = tmp_path / name
        (root / "etc").mkdir(parents=True)
        (root / "etc" / "os-release").write_text(
            f'VERSION_ID="{releasever}"\n', encoding="utf-8"
        )
        return root

    def request(root):
        return {
            "packages": ["package"],
            "repos": [],
            "architecture": "x86_64",
            "module-platform-id": "platform:el10",
            "root-dir": str(root),
        }

    root9 = make_root("root9", "9")
    lockfile = {"version": 1}
    solver = Solver()
    generated = new_manifest(mpp_module, lockfile_output=lockfile)
    generated.solver_factory = SolverFactory(solver)

    generated.depsolve(request(root9))

    entry = next(iter(lockfile["depsolves"].values()))
    assert entry["request"]["releasever"] == "9"
    assert "root-dir" not in entry["request"]
    assert solver.releasever == "9"

    replayed = new_manifest(mpp_module, lockfile_data=lockfile)
    replayed.solver_factory = None
    locked_packages = replayed.depsolve(request(root9))

    assert len(locked_packages) == 1
    assert locked_packages[0].checksum == "sha256:package"
    assert locked_packages[0].nevra == "package-1-1.x86_64"
    assert locked_packages[0].license_tag == "MIT"
    assert locked_packages[0].url == "https://example.com/package.rpm"

    root10 = make_root("root10", "10")
    replayed = new_manifest(mpp_module, lockfile_data=lockfile)
    replayed.solver_factory = SolverFactory(Solver())

    with pytest.raises(RuntimeError, match="Lockfile miss for depsolve"):
        replayed.depsolve(request(root10))


def test_container_index_is_part_of_lock_request(mpp_module, monkeypatch):
    class ResolvedManifest:
        digest = "sha256:manifest"

        @staticmethod
        def get_config_digest():
            return "sha256:config"

    class MainManifest:
        digest = "sha256:index"

        @staticmethod
        def resolve_list(_arch, _os, _variant, _transport):
            return ResolvedManifest()

    monkeypatch.setattr(
        mpp_module.ImageManifest, "load", lambda *_args, **_kwargs: MainManifest()
    )

    non_index_lockfile = {"version": 1}
    generated = new_manifest(mpp_module, lockfile_output=non_index_lockfile)
    generated.vars["arch"] = "x86_64"
    generated._process_container(container_stage(index=False))

    non_index_key, entry = next(iter(non_index_lockfile["containers"].items()))
    assert entry["request"]["index"] is False
    assert "index_digest" not in entry

    replayed = new_manifest(mpp_module, lockfile_data=non_index_lockfile)
    replayed.vars["arch"] = "x86_64"
    with pytest.raises(RuntimeError, match="Lockfile miss for container"):
        replayed._process_container(container_stage(index=True))

    index_lockfile = {"version": 1}
    generated = new_manifest(mpp_module, lockfile_output=index_lockfile)
    generated.vars["arch"] = "x86_64"
    generated._process_container(container_stage(index=True))

    index_key, entry = next(iter(index_lockfile["containers"].items()))
    assert entry["request"]["index"] is True
    assert entry["index_digest"] == "sha256:index"
    assert index_key != non_index_key

    monkeypatch.setattr(
        mpp_module.ImageManifest,
        "load",
        lambda *_args, **_kwargs: pytest.fail(
            "locked replay resolved the container image"
        ),
    )

    replayed = new_manifest(mpp_module, lockfile_data=non_index_lockfile)
    replayed.vars["arch"] = "x86_64"
    non_index_stage = container_stage(index=False)
    replayed._process_container(non_index_stage)

    assert replayed.sources["org.osbuild.skopeo"]["items"] == {
        "sha256:config": {
            "image": {
                "name": "example.com/image",
                "digest": "sha256:manifest",
            }
        }
    }
    assert "org.osbuild.skopeo-index" not in replayed.sources
    assert "manifest-lists" not in non_index_stage["inputs"]

    replayed = new_manifest(mpp_module, lockfile_data=index_lockfile)
    replayed.vars["arch"] = "x86_64"
    index_stage = container_stage(index=True)
    replayed._process_container(index_stage)

    assert replayed.sources["org.osbuild.skopeo-index"]["items"] == {
        "sha256:index": {"image": {"name": "example.com/image"}}
    }
    assert index_stage["inputs"]["manifest-lists"] == {
        "type": "org.osbuild.files",
        "origin": "org.osbuild.source",
        "references": ["sha256:index"],
    }

    replayed = new_manifest(mpp_module, lockfile_data=index_lockfile)
    replayed.vars["arch"] = "x86_64"
    with pytest.raises(RuntimeError, match="Lockfile miss for container"):
        replayed._process_container(container_stage(index=False))


def test_ostree_lockfile_generation_and_replay(mpp_module, monkeypatch):
    remote = {"url": "https://example.com/ostree/repo"}
    ref = "example/aarch64/stable"
    checksum = "a" * 64
    calls = []

    monkeypatch.setattr(
        mpp_module.ostree,
        "cli",
        lambda *args, **kwargs: calls.append(("cli", args, kwargs)),
    )
    monkeypatch.setattr(
        mpp_module.ostree,
        "setup_remote",
        lambda *args, **kwargs: calls.append(("setup_remote", args, kwargs)),
    )
    monkeypatch.setattr(
        mpp_module.ostree,
        "rev_parse",
        lambda *args, **kwargs: calls.append(("rev_parse", args, kwargs)) or checksum,
    )

    lockfile = {"version": 1}
    generated = new_manifest(mpp_module, lockfile_output=lockfile)
    generated_stage = ostree_stage(remote, ref, target="installed/ref")
    generated._process_ostree_commits(generated_stage)

    entry = next(iter(lockfile["ostree_commits"].values()))
    assert entry == {
        "request": {"remote": remote, "ref": ref},
        "checksum": checksum,
    }
    assert [call[0] for call in calls] == [
        "cli",
        "setup_remote",
        "cli",
        "rev_parse",
    ]

    def fail_resolution(*_args, **_kwargs):
        pytest.fail("locked replay resolved the OSTree commit")

    monkeypatch.setattr(mpp_module.ostree, "cli", fail_resolution)
    monkeypatch.setattr(mpp_module.ostree, "setup_remote", fail_resolution)
    monkeypatch.setattr(mpp_module.ostree, "rev_parse", fail_resolution)

    replayed = new_manifest(mpp_module, lockfile_data=lockfile)
    replayed_stage = ostree_stage(remote, ref, target="replayed/ref")
    replayed._process_ostree_commits(replayed_stage)

    assert replayed.sources["org.osbuild.ostree"]["items"] == {
        checksum: {"remote": remote}
    }
    assert replayed_stage["inputs"]["commits"]["references"] == {
        checksum: {"ref": "replayed/ref"}
    }

    replayed = new_manifest(mpp_module, lockfile_data=lockfile)
    with pytest.raises(RuntimeError, match="Lockfile miss for ostree"):
        replayed._process_ostree_commits(ostree_stage(remote, "example/aarch64/next"))
