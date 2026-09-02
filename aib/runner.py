import contextlib
import os
import shutil
import shlex
import subprocess
import sys
import threading
import time

from . import log
from . import exceptions
from .execmode import ExecMode
from .progress import OSBuildProgressMonitor

# Runner is a mechanism to run commands either as the current user or as
# root. How root is reached (directly, via sudo, or not at all because the
# tools handle rootless operation themselves) is decided by ExecMode.


class Runner:
    def __init__(self, args):
        self.mode = ExecMode.current()
        self.keepalive_thread = None

    def _start_sudo_keepalive(self):
        def keepalive():
            while True:
                time.sleep(300)
                # Update timestamp without prompting
                subprocess.call(
                    ["sudo", "-n", "-v"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

        self.keepalive_thread = threading.Thread(target=keepalive, daemon=True)
        self.keepalive_thread.start()

    def ensure_sudo(self):
        if not self.mode.uses_sudo:
            return

        if self.keepalive_thread and self.keepalive_thread.is_alive():
            return

        # Update sudo timestamp, prompting if necessary
        subprocess.check_call(["sudo", "-v"])
        self._start_sudo_keepalive()

    def _run(
        self,
        cmdline,
        as_root=False,
        with_progress=False,
        capture_output=False,
        stdout_to_devnull=False,
        verbose=False,
        log_file=None,
    ):
        if as_root:
            if self.mode.uses_sudo:
                self.ensure_sudo()
            cmdline = self.mode.run_prefix + cmdline

        if with_progress:
            log.debug("Running with progress: %s", shlex.join(cmdline))

            if log_file is None:
                raise exceptions.MissingLogFile()

            progress_monitor = OSBuildProgressMonitor(
                log_file=log_file, verbose=verbose
            )

            try:
                return_code = progress_monitor.run(cmdline)
                if return_code != 0:
                    sys.exit(return_code)
            except (subprocess.CalledProcessError, OSError) as e:
                log.error("Error running osbuild with progress: %s", e)
                sys.exit(1)
        else:
            log.debug("Running: %s", shlex.join(cmdline))

            try:
                with contextlib.ExitStack() as cn:
                    kwargs = {}
                    if stdout_to_devnull:
                        kwargs["stdout"] = subprocess.DEVNULL
                    elif capture_output:
                        kwargs["capture_output"] = True
                    elif log_file is not None:
                        f = cn.enter_context(open(log_file, "w", encoding="utf-8"))
                        kwargs["stdout"] = f
                        kwargs["stderr"] = f
                    r = subprocess.run(cmdline, check=True, **kwargs)
                    if capture_output:
                        return r.stdout.decode("utf-8").rstrip()
            except subprocess.CalledProcessError:
                sys.exit(1)  # cmd will have printed the error

    # Run the commandline as root, i.e. with sudo if not already root.
    # Note: In the rootless case we never actually run as root, and all launched
    # tools are supposed to correctly handle this.
    def run_as_root(
        self,
        cmdline,
        progress=False,
        capture_output=False,
        stdout_to_devnull=False,
        verbose=False,
        log_file=None,
    ):
        return self._run(
            cmdline,
            capture_output=capture_output,
            as_root=True,
            with_progress=progress,
            stdout_to_devnull=stdout_to_devnull,
            verbose=verbose,
            log_file=log_file,
        )

    # Run commandline as the current user.
    def run_as_user(
        self,
        cmdline,
        capture_output=False,
    ):
        return self._run(cmdline, as_root=False, capture_output=capture_output)

    # Tries to remove a path, falling back to a privileged helper for trees
    # that may hold files owned by root or by mapped subuids.
    def rm_rf(self, path):
        if not os.path.exists(path):
            return

        try:
            shutil.rmtree(path)
            return
        except (OSError, PermissionError) as e:
            last_err = e

        prefix = self.mode.reap_prefix
        if prefix:
            if self.mode.uses_sudo:
                self.ensure_sudo()
            self.run_as_user(prefix + ["rm", "-rf", path])
            return  # Above will exit on error

        raise last_err

    # Move a build artifact to a destination, owned by the current user. Only
    # the sudo case needs a chown: elsewhere the artifact is already ours (real
    # root, or our uid inside the tool's user namespace).
    def move_chown(self, src, dst):
        if self.mode.uses_sudo:
            self.ensure_sudo()
            self.run_as_root(["chown", f"{os.getuid()}:{os.getgid()}", src])
            self.run_as_root(["mv", src, dst])
        else:
            shutil.move(src, dst)
