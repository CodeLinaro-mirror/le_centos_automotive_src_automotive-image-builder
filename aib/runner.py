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
from .progress import OSBuildProgressMonitor

# Runner is a mechanism to run commands in a different context.
# There are two primary types of contexts:
#  - Run on the host, or in a container
#  - Run as root, or as the current user
#
# These also combine, for example as the current user, but inside a
# rootful container. On top of this, sometimes you need special
# privileges when running a container, to e.g. allow osbuild to run in
# the container.
#
# There are many different reasons for running in a context. Here are some:
# - Running osbuild on the host needs to run as root
# - Run in a container because osbuild is not installed on the host
# - Run as root, because we want to use rootfull podman/skopeo
# - Run as root, because earlier runs produced root-owned files we need to access
# - Run as root, to get rootful podman, but run as user inside the container to produce correctly owned files


class Volumes(set):
    def __init__(self):
        super(Volumes, self).__init__()

    def add_volume(self, directory):
        self.add(os.path.realpath(directory))

    def add_volume_for(self, file):
        self.add(os.path.dirname(os.path.realpath(file)))


class Runner:
    def __init__(self, args):
        self.use_container = args.container or args.user_container
        self.container_needs_root = not args.user_container
        self.container_image = args.container_image_name
        self.container_autoupdate = args.container_autoupdate
        self.use_sudo_for_root = os.getuid() != 0
        self.keepalive_thread = None
        self.volumes = Volumes()
        for d in args.include_dirs:
            self.add_volume(d)

    def _collect_podman_args(
        self,
        rootless,
        as_user_in_container,
        need_osbuild_privs,
        need_selinux_privs,
        extra_volumes,
    ):
        podman_args = [
            "--rm",
            "--workdir",
            os.path.realpath(os.getcwd()),
            "--read-only=false",
        ]

        for v in sorted(self.volumes):
            podman_args.append("-v")
            podman_args.append(f"{v}:{v}")

        if extra_volumes:
            for k, v in sorted(extra_volumes.items()):
                podman_args.append("-v")
                podman_args.append(f"{k}:{v}")

        if self.container_autoupdate:
            podman_args.append("--pull=newer")

        if rootless:
            # For rootless --privileges is quite different. Its not a
            # global security problem, and allows things to work.
            podman_args = podman_args + [
                "--privileged",
            ]

        if need_osbuild_privs and not rootless:
            podman_args = podman_args + [
                "--cap-add=MAC_ADMIN",
                "--security-opt",
                "label=type:unconfined_t",
                "--privileged",
            ]

        if need_selinux_privs and not rootless:
            podman_args = podman_args + [
                "--privileged",
            ]

        if as_user_in_container:
            podman_args = podman_args + [
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--security-opt",
                "label=disable",
            ]

        return podman_args

    @property
    def conman(self):
        if shutil.which("podman") is None and shutil.which("docker") is not None:
            return "docker"
        return "podman"

    def add_volume(self, directory):
        self.volumes.add_volume(directory)

    def add_volume_for(self, file):
        self.volumes.add_volume_for(file)

    def _add_container_cmd(
        self,
        rootless,
        as_user_in_container,
        need_osbuild_privs,
        need_selinux_privs,
        extra_volumes,
    ):
        return (
            [
                self.conman,
                "run",
            ]
            + self._collect_podman_args(
                rootless,
                as_user_in_container,
                need_osbuild_privs,
                need_selinux_privs,
                extra_volumes,
            )
            + [self.container_image]
        )

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
        if not self.use_sudo_for_root:
            return

        if self.keepalive_thread and self.keepalive_thread.is_alive():
            return

        # Update sudo timestamp, prompting if necessary
        subprocess.check_call(["sudo", "-v"])
        self._start_sudo_keepalive()

    def _run(
        self,
        cmdline,
        use_container=False,
        as_root=False,
        as_user_in_container=False,
        extra_volumes=None,
        need_osbuild_privs=False,
        need_selinux_privs=False,
        with_progress=False,
        capture_output=False,
        stdout_to_devnull=False,
        verbose=False,
        log_file=None,
    ):
        if use_container:
            cmdline = (
                self._add_container_cmd(
                    not as_root,
                    as_user_in_container,
                    need_osbuild_privs,
                    need_selinux_privs,
                    extra_volumes,
                )
                + cmdline
            )

        if as_root and self.use_sudo_for_root:
            self.ensure_sudo()

            allowed_env_vars = [
                "REGISTRY_AUTH_FILE",
                "CONTAINERS_CONF",
                "CONTAINERS_REGISTRIES_CONF",
                "CONTAINERS_STORAGE_CONF",
            ]

            sudo_cmd = [
                "sudo",
                "--preserve-env={}".format(",".join(allowed_env_vars)),
            ]
            cmdline = sudo_cmd + cmdline

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

    # Run the commandline as root, i.e. with sudo if not already root
    def run_as_root(
        self,
        cmdline,
        capture_output=False,
    ):
        return self._run(
            cmdline, capture_output=capture_output, use_container=False, as_root=True
        )

    # Run the commandline in a container, if container use is enabled, otherwise
    # just runs as root.
    #
    # For rootful containers, the container runs as root,
    # For rootless it runs as the user, but in the container it looks as root.
    #
    # By default the container is unprivileged (although for rootless containers
    # --privileged is passed, it just means something else there).
    # However if need_osbuild_privs is true, then the container has enough privileges
    # to run osbuilt inside it.
    def run_in_container(
        self,
        cmdline,
        need_osbuild_privs=False,
        need_selinux_privs=False,
        progress=False,
        capture_output=False,
        stdout_to_devnull=False,
        verbose=False,
        log_file=None,
        extra_volumes=None,
    ):
        use_container = self.use_container
        if use_container:
            as_root = self.container_needs_root
        else:
            as_root = True
        return self._run(
            cmdline,
            capture_output=capture_output,
            use_container=use_container,
            as_root=as_root,
            need_osbuild_privs=need_osbuild_privs,
            need_selinux_privs=need_selinux_privs,
            with_progress=progress,
            stdout_to_devnull=stdout_to_devnull,
            verbose=verbose,
            log_file=log_file,
            extra_volumes=extra_volumes,
        )

    # Run commandline as user, either directly, or in a container, it
    # container use is enabled.
    # If a rootful container is used, then --user is passed to ensure
    # the the process inside the container runs as the current user.
    def run_as_user(
        self,
        cmdline,
        capture_output=False,
    ):
        use_container = self.use_container
        as_root = use_container and self.container_needs_root
        as_user_in_container = as_root

        return self._run(
            cmdline,
            use_container=use_container,
            as_root=as_root,
            as_user_in_container=as_user_in_container,
            capture_output=capture_output,
        )

    # Tries to remove a path, if needed (and allowed) with sudo
    def rm_rf(self, path):
        if not os.path.exists(path):
            return

        try:
            shutil.rmtree(path)
            return
        except (OSError, PermissionError) as e:
            last_err = e

        # If allowed (not user-container) and useful (not already root), try sudo:
        if self.container_needs_root and self.use_sudo_for_root:
            self.run_as_root(["rm", "-rf", path])
            return  # Above will exit on error

        raise last_err

    # Move a file (possibly root owned) to a destination and chown it to the
    # current user
    def move_chown(self, src, dst):
        if not self.container_needs_root:
            subprocess.run(["mv", src, dst], check=True)
        else:
            self.run_as_root(["chown", f"{os.getuid()}:{os.getgid()}", src])
            self.run_as_root(["mv", src, dst])
