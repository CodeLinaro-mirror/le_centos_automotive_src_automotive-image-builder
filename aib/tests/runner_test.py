import pytest
from unittest.mock import MagicMock, patch

import aib.main  # noqa: F401
from aib import AIBParameters
from aib import exceptions
from aib.arguments import parse_args
from aib.runner import Runner


BASE_DIR = "/usr/lib/automotive-image-builder"


class AnyListContaining(str):
    def __eq__(self, other):
        return self in other


class ListNotContaining(str):
    def __eq__(self, other):
        for o in other:
            if o == str(self):
                return False
        return True


def make_runner(args=None):
    return Runner(
        AIBParameters(
            parse_args(args or []),
            base_dir=BASE_DIR,
        )
    )


@pytest.mark.parametrize("use_sudo_for_root", [True, False])
@patch("aib.runner.subprocess")
def test_run_args_root(subprocess_mock, use_sudo_for_root):
    subprocess_run = MagicMock()
    subprocess_mock.run = subprocess_run
    runner = make_runner()
    runner.use_sudo_for_root = use_sudo_for_root
    runner.ensure_sudo = MagicMock()

    cmd = ["touch", "example"]
    runner.run_as_root(cmd)

    # run_as_root always calls with capture_output=False (no return needed)
    subprocess_run.assert_called_once_with(ListNotContaining("podman"), check=True)
    if use_sudo_for_root:
        subprocess_run.assert_called_once_with(AnyListContaining("sudo"), check=True)


@pytest.mark.parametrize("use_sudo_for_root", [True, False])
@pytest.mark.parametrize("verbose", [True, False])
@patch("aib.runner.subprocess")
def test_run_args_container_without_progress_no_capture(
    subprocess_mock,
    use_sudo_for_root,
    verbose,
):
    """Test run_as_root without progress and without capturing output."""
    subprocess_run = MagicMock()
    subprocess_mock.run = subprocess_run

    runner = make_runner()
    runner.use_sudo_for_root = use_sudo_for_root
    runner.ensure_sudo = MagicMock()

    cmd = ["touch", "example"]
    runner.run_as_root(cmd, progress=False, capture_output=False, verbose=verbose)

    subprocess_run.assert_called_once_with(ListNotContaining("podman"), check=True)

    if use_sudo_for_root:
        subprocess_run.assert_called_once_with(AnyListContaining("sudo"), check=True)
    else:
        subprocess_run.assert_called_once_with(ListNotContaining("sudo"), check=True)


@pytest.mark.parametrize("use_sudo_for_root", [True, False])
@pytest.mark.parametrize("verbose", [True, False])
@patch("aib.runner.subprocess")
def test_run_args_container_without_progress_with_capture(
    subprocess_mock,
    use_sudo_for_root,
    verbose,
):
    """Test run_as_root without progress but with capturing output."""
    subprocess_run = MagicMock()
    subprocess_mock.run = subprocess_run

    runner = make_runner()
    runner.use_sudo_for_root = use_sudo_for_root
    runner.ensure_sudo = MagicMock()

    cmd = ["touch", "example"]
    runner.run_as_root(cmd, progress=False, capture_output=True, verbose=verbose)

    # When capturing, subprocess.run should have capture_output=True
    subprocess_run.assert_called_once_with(
        ListNotContaining("podman"),
        capture_output=True,
        check=True,
    )

    if use_sudo_for_root:
        subprocess_run.assert_called_once_with(
            AnyListContaining("sudo"), capture_output=True, check=True
        )
    else:
        subprocess_run.assert_called_once_with(
            ListNotContaining("sudo"), capture_output=True, check=True
        )


@pytest.mark.parametrize("use_sudo_for_root", [True, False])
@pytest.mark.parametrize("capture_output", [True, False])
@pytest.mark.parametrize("verbose", [True, False])
@patch("aib.runner.OSBuildProgressMonitor")
def test_run_args_container_with_progress(
    progress_monitor_mock,
    use_sudo_for_root,
    capture_output,
    verbose,
    tmp_path,
):
    # Setup progress monitor mock
    monitor_instance = MagicMock()
    monitor_instance.run.return_value = 0
    progress_monitor_mock.return_value = monitor_instance

    # Create a log file path
    log_file_path = str(tmp_path / "test.log")

    runner = make_runner()
    runner.use_sudo_for_root = use_sudo_for_root
    runner.ensure_sudo = MagicMock()

    cmd = ["touch", "example"]
    runner.run_as_root(
        cmd,
        progress=True,
        capture_output=capture_output,
        verbose=verbose,
        log_file=log_file_path,
    )

    # Progress monitor should be created and used
    progress_monitor_mock.assert_called_once_with(
        log_file=log_file_path, verbose=verbose
    )

    monitor_instance.run.assert_called_once_with(ListNotContaining("podman"))

    if use_sudo_for_root:
        monitor_instance.run.assert_called_once_with(AnyListContaining("sudo"))
    else:
        monitor_instance.run.assert_called_once_with(ListNotContaining("sudo"))


@pytest.mark.parametrize("use_sudo_for_root", [True, False])
@pytest.mark.parametrize("verbose", [True, False])
@patch("aib.runner.subprocess")
def test_run_args_osbuild_without_progress_no_capture(
    subprocess_mock,
    use_sudo_for_root,
    verbose,
):
    """Test run_as_root with osbuild privs, without progress and without capturing output."""
    subprocess_run = MagicMock()
    subprocess_mock.run = subprocess_run

    runner = make_runner()
    runner.use_sudo_for_root = use_sudo_for_root
    runner.ensure_sudo = MagicMock()

    cmd = ["touch", "example"]
    runner.run_as_root(
        cmd,
        progress=False,
        capture_output=False,
        verbose=verbose,
    )

    subprocess_run.assert_called_once_with(ListNotContaining("podman"), check=True)

    if use_sudo_for_root:
        subprocess_run.assert_called_once_with(AnyListContaining("sudo"), check=True)
    else:
        subprocess_run.assert_called_once_with(ListNotContaining("sudo"), check=True)


@pytest.mark.parametrize("use_sudo_for_root", [True, False])
@pytest.mark.parametrize("verbose", [True, False])
@patch("aib.runner.subprocess")
def test_run_args_osbuild_without_progress_with_capture(
    subprocess_mock,
    use_sudo_for_root,
    verbose,
):
    """Test run_as_root with osbuild privs, without progress but with capturing output."""
    subprocess_run = MagicMock()
    subprocess_mock.run = subprocess_run

    runner = make_runner()
    runner.use_sudo_for_root = use_sudo_for_root
    runner.ensure_sudo = MagicMock()

    cmd = ["touch", "example"]
    runner.run_as_root(
        cmd,
        progress=False,
        capture_output=True,
        verbose=verbose,
    )

    # When capturing, subprocess.run should have capture_output=True
    subprocess_run.assert_called_once_with(
        ListNotContaining("podman"),
        capture_output=True,
        check=True,
    )

    if use_sudo_for_root:
        subprocess_run.assert_called_once_with(
            AnyListContaining("sudo"), capture_output=True, check=True
        )
    else:
        subprocess_run.assert_called_once_with(
            ListNotContaining("sudo"), capture_output=True, check=True
        )


@pytest.mark.parametrize("use_sudo_for_root", [True, False])
@pytest.mark.parametrize("capture_output", [True, False])
@pytest.mark.parametrize("verbose", [True, False])
@patch("aib.runner.OSBuildProgressMonitor")
def test_run_args_osbuild_with_progress(
    progress_monitor_mock,
    use_sudo_for_root,
    capture_output,
    verbose,
    tmp_path,
):
    # Setup progress monitor mock
    monitor_instance = MagicMock()
    monitor_instance.run.return_value = 0
    progress_monitor_mock.return_value = monitor_instance

    # Create a log file path
    log_file_path = str(tmp_path / "test.log")

    runner = make_runner()
    runner.use_sudo_for_root = use_sudo_for_root
    runner.ensure_sudo = MagicMock()

    cmd = ["touch", "example"]
    runner.run_as_root(
        cmd,
        progress=True,
        capture_output=capture_output,
        verbose=verbose,
        log_file=log_file_path,
    )

    # Progress monitor should be created and used
    progress_monitor_mock.assert_called_once_with(
        log_file=log_file_path, verbose=verbose
    )

    monitor_instance.run.assert_called_once_with(ListNotContaining("podman"))

    if use_sudo_for_root:
        monitor_instance.run.assert_called_once_with(AnyListContaining("sudo"))
    else:
        monitor_instance.run.assert_called_once_with(ListNotContaining("sudo"))


@pytest.mark.parametrize("use_sudo_for_root", [True, False])
@pytest.mark.parametrize("verbose", [True, False])
@patch("aib.runner.OSBuildProgressMonitor")
def test_run_with_log_file(
    progress_monitor_mock,
    use_sudo_for_root,
    verbose,
    tmp_path,
):
    """Test that log_file parameter is correctly passed to OSBuildProgressMonitor."""
    # Setup progress monitor mock
    monitor_instance = MagicMock()
    monitor_instance.run.return_value = 0
    progress_monitor_mock.return_value = monitor_instance

    # Create a log file path
    log_file_path = str(tmp_path / "test.log")

    runner = make_runner()
    runner.use_sudo_for_root = use_sudo_for_root
    runner.ensure_sudo = MagicMock()

    cmd = ["touch", "example"]
    runner.run_as_root(
        cmd,
        progress=True,
        verbose=verbose,
        log_file=log_file_path,
    )

    # Progress monitor should be created and used
    progress_monitor_mock.assert_called_once_with(
        log_file=log_file_path, verbose=verbose
    )

    # Monitor should have been used
    monitor_instance.run.assert_called_once()


@pytest.mark.parametrize("use_sudo_for_root", [True, False])
@patch("aib.runner.subprocess")
def test_run_args_user(subprocess_mock, use_sudo_for_root):
    subprocess_run = MagicMock()
    subprocess_mock.run = subprocess_run
    runner = make_runner()
    runner.use_sudo_for_root = use_sudo_for_root
    runner.ensure_sudo = MagicMock()

    cmd = ["touch", "example"]
    runner.run_as_user(cmd)

    # run_as_user runs directly, never in a container and never as root
    subprocess_run.assert_called_once_with(ListNotContaining("podman"), check=True)
    subprocess_run.assert_called_once_with(ListNotContaining("sudo"), check=True)


def test_run_as_root_progress_without_log_file_raises_exception():
    runner = make_runner()
    runner.ensure_sudo = MagicMock()

    cmd = ["osbuild", "manifest.json"]

    # Should raise MissingLogFile when progress=True but log_file=None
    with pytest.raises(exceptions.MissingLogFile):
        runner.run_as_root(cmd, progress=True, log_file=None)


@patch("aib.runner.threading.Thread")
@patch("aib.runner.subprocess")
def test_ensure_sudo_success(subprocess_mock, thread_mock):
    """Test that ensure_sudo calls sudo -v and starts keepalive thread."""
    # Setup
    args = MagicMock()
    args.include_dirs = []

    runner = Runner(args)
    runner.use_sudo_for_root = True

    # Execution
    runner.ensure_sudo()

    # Verification
    subprocess_mock.check_call.assert_called_once_with(["sudo", "-v"])

    thread_mock.assert_called_once()
    call_args = thread_mock.call_args
    assert call_args.kwargs["daemon"] is True

    thread_instance = thread_mock.return_value
    thread_instance.start.assert_called_once()


def test_ensure_sudo_already_running():
    """Test that ensure_sudo does nothing if keepalive thread is alive."""
    args = MagicMock()
    args.include_dirs = []

    runner = Runner(args)
    runner.use_sudo_for_root = True

    # Mock existing thread
    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = True
    runner.keepalive_thread = mock_thread

    # We shouldn't need to mock subprocess because it shouldn't be called
    # But to be safe and catch regressions, we can patch it
    with patch("aib.runner.subprocess") as subprocess_mock:
        runner.ensure_sudo()
        subprocess_mock.check_call.assert_not_called()
