import pytest
import argparse

import aib.main  # noqa: F401
from aib.arguments import parse_args, parse_root_password, RootPasswordOptionPrefix


@pytest.mark.parametrize("arg_before_subcommand", [True, False])
@pytest.mark.parametrize(
    "subcommand,arg_name,arg_value,extra_args,expected_value",
    [
        (
            "build",
            "--container",
            [],
            ["--target", "qemu", "test.mpp.yml", "output"],
            True,
        ),
        (
            "build",
            "--include",
            ["/some/path"],
            ["--target", "qemu", "test.mpp.yml", "output.json"],
            "/some/path",
        ),
        ("list-distro", "--include", ["/some/path"], [], "/some/path"),
    ],
)
def test_args_work_before_and_after_subcommands(
    arg_before_subcommand, subcommand, arg_name, arg_value, extra_args, expected_value
):
    """Test that --container, and --include work both before and after subcommands."""
    if arg_before_subcommand:
        args = [arg_name] + arg_value + [subcommand] + extra_args
    else:
        args = [subcommand] + [arg_name] + arg_value + extra_args

    parsed = parse_args(args)

    # Derive attribute name from argument name
    attr_name = arg_name.removeprefix("--").replace("-", "_")
    attr_value = getattr(parsed, attr_name)

    # Check the argument was parsed correctly
    if isinstance(expected_value, bool):
        assert attr_value is expected_value
    elif isinstance(expected_value, str):
        # For list arguments like --include
        assert expected_value in attr_value


class TestParseRootPassword:

    @pytest.mark.parametrize(
        "input,error",
        [
            ("topsecretandactuallyhashed", argparse.ArgumentTypeError),
            ("unknown:topsecret", argparse.ArgumentTypeError),
        ],
    )
    def test_unsupported_prefix(self, input, error):
        with pytest.raises(error):
            parse_root_password(input)

    @pytest.mark.parametrize(
        "key,password", [("CUSTOM_PW", "topsecretandactuallyhashed"), ("CUSTOM_PW", "")]
    )
    def test_env_prefix(self, monkeypatch, key, password):
        monkeypatch.setenv(key, password)

        result = parse_root_password(f"{RootPasswordOptionPrefix.ENV.value}:{key}")
        assert result == password

    @pytest.mark.parametrize(
        "file,password",
        [
            (".pw-file", "topsecretandactuallyhashed"),
            ("file.txt", " withadditionalspaces     "),
        ],
    )
    def test_file_prefix(self, tmp_path, file, password):
        file_path = tmp_path / file
        file_path.write_text(password)

        result = parse_root_password(
            f"{RootPasswordOptionPrefix.FILE.value}:{file_path}"
        )
        assert result == password.strip()
