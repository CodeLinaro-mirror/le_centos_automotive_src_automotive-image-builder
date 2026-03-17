import pytest

import aib.main  # noqa: F401
from aib.arguments import parse_args
from aib.osbuild import create_osbuild_manifest, rewrite_manifest
from aib import AIBParameters
from aib import exceptions

BASE_DIR = "/usr/lib/automotive-image-builder"
INVALID_YAML = """
  # Bad indentation
  pipelines:

qm_rootfs:
"""


def test_create_manifest(tmp_path):
    manifest_file = tmp_path / "manifest.yml"
    manifest_file.write_text(INVALID_YAML)
    tar_file = tmp_path / "foo.tar"
    args = AIBParameters(
        args=parse_args(
            [
                "build",
                "--tar",
                "--osbuild-manifest",
                "output",
                manifest_file.as_posix(),
                tar_file.as_posix(),
            ]
        ),
        base_dir=BASE_DIR,
    )
    with pytest.raises(exceptions.ManifestParseError) as manifest_err:
        create_osbuild_manifest(
            args, tmpdir="/tmp", out="output", storage=None, runner=None
        )
    assert manifest_file.as_posix() in str(manifest_err)


def test_rewrite_manifest():
    with pytest.raises(exceptions.MissingSection) as pipelines_err:
        rewrite_manifest({"pipelines": []}, "/mock/path")
    assert "pipelines" in str(pipelines_err)


def test_missing_export():
    with pytest.raises(SystemExit) as argparse_err:
        AIBParameters(
            args=parse_args(["build", "out"]),
            base_dir=BASE_DIR,
        )
    assert argparse_err.value.code == 2
