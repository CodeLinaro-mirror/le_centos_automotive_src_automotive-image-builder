import pytest
import re

import aib.main  # noqa: F401 - Registers commands
from aib.arguments import parse_args
from aib import AIBParameters

BASEDIR = "/tmp/automotive-image-builder"


@pytest.mark.parametrize(
    "subcmd",
    [
        "list-distro",
        "list-targets",
        "build",
    ],
)
def test_valid_subcommands(subcmd):
    with pytest.raises(SystemExit) as e:
        parse_args([subcmd, "--help"])
    assert e.value.code == 0


def test_invalid_subcommand():
    with pytest.raises(SystemExit) as e:
        parse_args(["invalid", "--help"])
    assert e.value.code == 2


def test_no_subcommand(caplog):
    args = parse_args([])
    args.func(_args=args, _tmpdir="", _runner=None)
    assert "No subcommand specified, see --help for usage" in caplog.text


def test_build_required_positional(capsys):
    with pytest.raises(SystemExit) as e:
        parse_args(["build"])
    assert e.value.code == 2
    assert (
        "error: the following arguments are required: manifest, out"
        in capsys.readouterr().err
    )


@pytest.mark.parametrize(
    "includes",
    [
        [],
        ["dir1"],
        ["dir1", "dir2"],
    ],
)
def test_aib_paramters(includes):
    base_dir = "base_dir"
    argv = []
    for inc in includes:
        argv.extend(["--include", inc])
    args = AIBParameters(args=parse_args(argv), base_dir=base_dir)
    assert args.base_dir == base_dir
    assert args.include_dirs == [base_dir] + includes


@pytest.mark.parametrize(
    "logfile,build_dir,progress,expected_contains",
    [
        # Custom logfile path
        ("/custom/path/build.log", "/build", True, "/custom/path/build.log"),
        # Default logfile with build_dir
        (None, "/build", True, "/build/automotive-image-builder-"),
        # No logfile when progress is disabled and no logfile specified
        (None, "/build", False, None),
        # Logfile specified but progress disabled (should still return logfile)
        ("/custom/log.log", "/build", False, "/custom/log.log"),
    ],
)
def test_aib_parameters_log_file_property(
    logfile, build_dir, progress, expected_contains
):
    """Test AIBParameters.log_file property returns correct path."""
    argv = ["build", "--target", "qemu", "manifest", "out"]

    if logfile:
        argv.extend(["--logfile", logfile])

    if build_dir:
        argv.extend(["--build-dir", build_dir])

    if progress:
        argv.append("--progress")

    args = parse_args(argv)
    params = AIBParameters(args=args, base_dir="")

    if expected_contains is None:
        assert params.log_file("/tmp") is None
    else:
        log_file = params.log_file("/tmp")
        assert log_file is not None
        assert expected_contains in log_file

        # If it's a generated path, verify it has the timestamp format
        if "automotive-image-builder-" in expected_contains and logfile is None:
            # Should match pattern: automotive-image-builder-YYYYMMDD-HHMMSS.log
            pattern = r"automotive-image-builder-\d{8}-\d{6}\.log"
            assert re.search(
                pattern, log_file
            ), f"Log file path {log_file} doesn't match expected format"


def test_aib_parameters_log_file_property_no_build_dir():
    """Test AIBParameters.log_file property when build_dir is not set but progress is enabled."""
    argv = ["build", "--target", "qemu", "--progress", "manifest", "out"]

    args = parse_args(argv)
    params = AIBParameters(args=args, base_dir="")

    # Should return a path n tmpdir when build_dir is not set and progress is passed
    assert "/tmp" in params.log_file("/tmp")
