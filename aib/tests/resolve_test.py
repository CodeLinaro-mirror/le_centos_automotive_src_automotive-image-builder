import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

from aib import main
from aib.runner import Runner


def test_resolve_generates_user_owned_lockfile(tmp_path):
    output = tmp_path / "image.lock"
    args = SimpleNamespace(
        simple_manifest=str(tmp_path / "image.aib.yml"),
        manifest=str(tmp_path / "simple.mpp.yml"),
        output=str(output),
    )
    runner = Mock(spec=Runner)
    storage = Mock()

    with (
        patch.object(main.ContainerStorage, "from_args", return_value=storage),
        patch.object(main, "create_osbuild_manifest") as create_manifest,
    ):
        main.resolve(args, tmp_path, runner)

    assert args.mode == "bootc"
    assert args.generate_lockfile == os.path.abspath(output)
    create_manifest.assert_called_once_with(
        args, tmp_path, os.path.join(tmp_path, "osbuild.json"), runner, storage
    )
    runner.run_as_root.assert_called_once_with(
        ["chown", f"{os.getuid()}:{os.getgid()}", args.generate_lockfile]
    )
