import json
import os
import shlex
import subprocess
import shutil
import tempfile
import textwrap
from pathlib import Path
from .globals import default_bib_container

from .utils import (
    detect_initrd_compression,
    create_cpio_archive,
)
from . import log
from .exceptions import (
    PodmanCommandFailed,
    UnsupportedImageType,
    InitramfsNotFound,
)


def run_cmd(
    args,
    capture_output=False,
    with_sudo=True,
    return_pipe=False,
    stdin_pipe=None,
    stdout_pipe=None,
    stderr_pipe=None,
    check=False,
):
    allowed_env_vars = [
        "REGISTRY_AUTH_FILE",
        "CONTAINERS_CONF",
        "CONTAINERS_REGISTRIES_CONF",
        "CONTAINERS_STORAGE_CONF",
    ]

    if with_sudo and os.getuid() != 0:
        sudo_path = shutil.which("sudo")
        if sudo_path is None:
            raise FileNotFoundError("sudo command not found in PATH")
        cmdline = [
            sudo_path,
            "--preserve-env={}".format(",".join(allowed_env_vars)),
        ] + args
    else:
        cmdline = args

    log.debug("Running: %s", shlex.join(cmdline))

    if return_pipe:
        # Return stdout pipe for streaming
        process = subprocess.Popen(cmdline, stdout=subprocess.PIPE, stdin=stdin_pipe)
        return process.stdout

    should_check = check or capture_output
    try:
        if capture_output:
            r = subprocess.run(
                cmdline, capture_output=True, stdin=stdin_pipe, check=should_check
            )
        else:
            r = subprocess.run(
                cmdline,
                stdin=stdin_pipe,
                stdout=stdout_pipe,
                stderr=stderr_pipe,
                check=should_check,
            )
    except subprocess.CalledProcessError as e:
        error_msg = (e.stderr or b"").decode("utf-8").rstrip() if e.stderr else ""
        raise PodmanCommandFailed(shlex.join(args), error_msg) from e

    if capture_output:
        return r.stdout.decode("utf-8").rstrip()
    return r.returncode


def run_podman_cmd(
    container,
    volumes,
    args,
    podman_args=None,
    with_sudo=True,
    cmd_prefix=None,
    stdout_pipe=None,
    check=False,
    storage=None,
):
    cmd = [
        "podman",
        "run",
        "--rm",
        "--security-opt",
        "label=type:unconfined_t",
        "-ti",
    ]
    if storage:
        cmd += storage.args()
    if cmd_prefix:
        cmd = cmd_prefix + cmd
    if podman_args:
        cmd += podman_args

    for k, v in sorted(volumes.items()):
        cmd.append("-v")
        cmd.append(f"{str(v)}:{k}")

    cmd.append(container)
    cmd += args

    return run_cmd(
        cmd,
        stdout_pipe=stdout_pipe,
        check=check,
        with_sudo=with_sudo,
    )


class ContainerStorage:
    def __init__(self, storage=None, tmpdir="/tmp", user_container=False):
        self.with_sudo = not user_container
        state = ContainerStorageState.query(not user_container)
        if storage:
            self.storage = storage
        else:
            self.storage = state.graphroot
        self.runroot = state.runroot
        self.driver = state.driver
        self.tmpdir = tmpdir
        self.tmp_storage = os.path.join(tmpdir, "aib-containers-store")
        self.tmp_runroot = os.path.join(tmpdir, "aib-containers-store-run")
        self.config_path = None

    @classmethod
    def from_args(cls, args, tmpdir):
        return ContainerStorage(args.container_storage, tmpdir, args.user_container)

    def args(self):
        return [f"--root={self.tmp_storage}", f"--imagestore={self.storage}"]

    def podman(self):
        return ["podman", f"--root={self.tmp_storage}", f"--imagestore={self.storage}"]

    def skopeo(self, image_name):
        return f"containers-storage:[{self.driver}@{self.storage}+{self.runroot}]{image_name}"

    def get_config_path(self):
        if self.config_path is None:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=self.tmpdir,
                prefix="storage-",
                suffix=".conf",
                delete=False,
            ) as tmpfile:
                config_content = textwrap.dedent(
                    f"""\
                    [storage]
                    driver = "{self.driver}"
                    graphroot = "{self.tmp_storage}"
                    runroot = "{self.tmp_runroot}"

                    [storage.options]
                    additionalimagestores = [
                    "{self.storage}"
                    ]
                    """
                )
                tmpfile.write(config_content)

            self.config_path = tmpfile.name

        return self.config_path

    def __str__(self):
        parts = []
        parts.append(f"storage={self.storage}")
        parts.append(f"tmp_storage={self.tmp_storage}")
        parts.append(f"with_sudo={self.with_sudo}")
        return f"ContainerStorage({', '.join(parts)})"


class PodmanImageMount:
    """Context manager for mounting and unmounting podman images."""

    def __init__(self, image, with_sudo=True, writable=False, commit_image=None):
        self.image = image
        self.mount_path = None
        self.with_sudo = with_sudo
        self.writable = writable
        self.commit_image = commit_image
        self.container_id = None
        self.image_id = None

    def __enter__(self):
        if self.writable:
            # Create a container from the image
            self.container_id = self.capture(["podman", "create", self.image]).strip()
            # Mount the container
            self.mount_path = self.capture(
                ["podman", "mount", self.container_id]
            ).strip()
        else:
            # Mount the image directly (read-only)
            self.mount_path = self.capture(
                ["podman", "image", "mount", self.image]
            ).strip()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.mount_path:
            if self.writable and self.container_id:
                # Unmount the container
                self.capture(["podman", "unmount", self.container_id])
                # Commit the container to a new image if requested
                if not exc_type:
                    cmd = ["podman", "commit", self.container_id]
                    if self.commit_image:
                        cmd = cmd + [self.commit_image]
                    self.image_id = self.capture(cmd)
                # Remove the container
                self.capture(["podman", "rm", self.container_id])
            else:
                # Unmount the image
                self.capture(["podman", "image", "unmount", self.image])

    def _ensure_mounted(self):
        """Ensure the image is mounted, raise RuntimeError if not."""
        if not self.mount_path:
            raise RuntimeError("Image not mounted - use within 'with' statement")

    def _get_full_path(self, path):
        """Convert a path to a full path within the mounted image."""
        given_path = Path(path)
        return str(Path(self.mount_path) / given_path.relative_to(given_path.anchor))

    def run(
        self, cmd, stdin_pipe=None, stdout_pipe=None, stderr_pipe=None, check=False
    ):
        return run_cmd(
            cmd,
            False,
            with_sudo=self.with_sudo,
            stdin_pipe=stdin_pipe,
            stdout_pipe=stdout_pipe,
            stderr_pipe=stderr_pipe,
            check=check,
        )

    def capture(self, cmd):
        return run_cmd(cmd, True, with_sudo=self.with_sudo)

    def read_file(self, path):
        """Read a file from the mounted image."""
        self._ensure_mounted()
        file_path = self._get_full_path(path)
        return self.capture(["cat", file_path])

    def has_file(self, path):
        """Check if a file exists at the given path in the mounted image."""
        self._ensure_mounted()
        file_path = self._get_full_path(path)
        return self.run(["test", "-f", file_path]) == 0

    def open_file(self, path):
        """Open a file from the mounted image and return a byte stream."""
        self._ensure_mounted()
        file_path = self._get_full_path(path)
        return run_cmd(["cat", file_path], with_sudo=self.with_sudo, return_pipe=True)

    def copy_out_file(self, source_path, dest_path):
        """Copy a file from the mounted image to a destination path on disk."""
        self._ensure_mounted()

        with self.open_file(source_path) as source_stream:
            with open(dest_path, "wb") as dest_file:
                shutil.copyfileobj(source_stream, dest_file)

    def read_dir(self, path):
        """List files in a directory within the mounted image."""
        self._ensure_mounted()
        dir_path = self._get_full_path(path)
        output = self.capture(["ls", "-1", dir_path])
        return output.split("\n") if output.strip() else []

    def get_kernel_subdir(self):
        self._ensure_mounted()
        return self.read_dir("/usr/lib/modules")[0]

    def get_ostree_initrd(self):
        kernel_subdir = self.get_kernel_subdir()
        ostree_boot_dir = "/usr/lib/ostree-boot"
        ostree_boot_files = self.read_dir(ostree_boot_dir)
        initrd_file = next(
            (
                f
                for f in ostree_boot_files
                if f.startswith(f"initramfs-{kernel_subdir}.img-")
            ),
            None,
        )
        if initrd_file:
            return os.path.join(ostree_boot_dir, initrd_file)
        else:
            return None

    def copy_in_file(self, source_path, dest_path):
        """Copy a file from the host filesystem into the mounted image."""
        self._ensure_mounted()

        dest_file_path = self._get_full_path(dest_path)

        with open(source_path, "rb") as source_file:
            self.run(
                ["tee", dest_file_path],
                stdin_pipe=source_file,
                stdout_pipe=subprocess.DEVNULL,
                check=True,
            )

    def link_file(self, source_path, dest_path):
        """Copy a file from the host filesystem into the mounted image."""
        self._ensure_mounted()

        source_file_path = self._get_full_path(source_path)
        dest_file_path = self._get_full_path(dest_path)

        self.run(
            ["ln", "-f", source_file_path, dest_file_path],
            check=True,
        )


def podman_image_exists(image):
    return run_cmd(["podman", "image", "exists", image]) == 0


def podman_image_rm(image):
    return run_cmd(["podman", "image", "rm", image]) == 0


def parse_shvars(content):
    result = {}
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for tok in shlex.split(line):
            if "=" in tok:
                k, v = tok.split("=", 1)
                result[k] = v
    return result


class TemporaryContainer:
    """Context manager for temporary container images.
    The container image is auto-removed when exiting the context.

    Usage:
        with TemporaryContainer(name="temp-image") as container:
            # Use the container name
            podman_run_something(container)
        # Container is automatically removed here
    """

    def __init__(self, name, cleanup=True):
        """Initialize temporary container context manager.

        Args:
            name: The container image name/tag to track
            cleanup: If True, remove the container on exit. If False, leave it.
                     Defaults to True.
        """
        self.name = name
        self.cleanup_enabled = cleanup
        self._removed = False

    def __enter__(self):
        """Enter the context and return the container name."""
        return self.name

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context and remove the container image if cleanup is enabled."""
        if self.cleanup_enabled:
            self.cleanup()

    def cleanup(self):
        """Remove the container image if it exists."""
        if self._removed:
            return

        try:
            if podman_image_exists(self.name):
                log.debug("Removing temporary container: %s", self.name)
                podman_image_rm(self.name)
            self._removed = True
        except Exception as e:
            log.warning("Failed to remove temporary container %s: %s", self.name, e)

    def __str__(self):
        return self.name


class ContainerInfo:
    def __init__(self, name, build_info):
        self.name = name
        self.build_info = build_info

    def __str__(self):
        return f"{self.name}({self.build_info})"


def podman_image_info(image):
    if not podman_image_exists(image):
        return None
    build_info = None
    try:
        with PodmanImageMount(image) as mount:
            content = mount.read_file("/etc/build-info")
            build_info = parse_shvars(content)
    except (PodmanCommandFailed, RuntimeError, ValueError) as e:
        log.info("No build info in %s: %s", image, e)
    return ContainerInfo(image, build_info)


def podman_run_bootc_image_builder(
    bib_container,
    build_container,
    bootc_container,
    build_type,
    dest_path,
    in_vm,
    verbose,
):
    state = ContainerState.query()

    # If we're in an a-i-b container and bc-i-b exists there, lets not launch nested containers.
    if (
        state.in_container
        and bib_container == default_bib_container
        and os.path.exists("/usr/bin/bootc-image-builder")
    ):
        bib_container = "/usr/bin/bootc-image-builder"

    if build_type == "raw":
        src_path = "image/disk.raw"
    elif build_type == "qcow2":
        src_path = "qcow2/disk.qcow2"
    elif build_type == "vmdk":
        src_path = "vmdk/disk.vmdk"
    elif build_type == "vpc":
        src_path = "vpc/disk.vpc"
    elif build_type == "ovf":
        src_path = "ovf/disk.ovf"
    else:
        raise UnsupportedImageType(build_type)

    with tempfile.TemporaryDirectory(
        prefix="automotive-image-builder-", dir="/var/tmp"
    ) as tmpdir:
        try:
            # To easily test non-containerized bc-i-b builds, parse
            # absolute paths as binary name:
            use_container = not bib_container.startswith("/")

            args = [
                "--build-container",
                build_container,
                "--progress",
                "verbose",
                "--type",
                build_type,
                bootc_container,
            ]
            if in_vm:
                args.append("--in-vm")
            if use_container:
                volumes = {
                    "/output": tmpdir,
                    "/var/lib/containers/storage": "/var/lib/containers/storage",
                }
                res = run_podman_cmd(
                    bib_container,
                    volumes,
                    args,
                    podman_args=["--privileged", "--network=none"],
                    stdout_pipe=None if verbose else subprocess.DEVNULL,
                )
            else:
                storedir = os.path.join(tmpdir, "store")
                os.mkdir(storedir)
                rpmmddir = os.path.join(tmpdir, "rpmmd")
                os.mkdir(rpmmddir)
                args += ["--store", storedir, "--rpmmd", rpmmddir]
                res = run_cmd(
                    [bib_container, "--output", tmpdir] + args,
                    stdout_pipe=None if verbose else subprocess.DEVNULL,
                )

            if res == 0:
                src = os.path.join(tmpdir, src_path)
                log.debug("Copying: %s to %s", src, dest_path)
                run_cmd(["cp", src, dest_path])
            return res

        finally:
            # Need sudo to have permissions to clean up the tmpdir
            run_cmd(["rm", "-rf", tmpdir])


def podman_bootc_inject_pubkey(
    src_container, dest_container, pub_key, build_container, verbose
):
    with tempfile.TemporaryDirectory(prefix="initrd-append-") as td:
        td = Path(td)

        # Extract the initrd
        extracted_initrd = td / "initrd"

        with PodmanImageMount(src_container) as mount:
            # Collect info on src_container
            kdir = mount.get_kernel_subdir()
            src_is_aboot = mount.has_file(f"/usr/lib/modules/{kdir}/aboot.img")

            # Extract initrd
            ostree_initrd_path = mount.get_ostree_initrd()
            if not ostree_initrd_path:
                raise InitramfsNotFound(src_container)
            mount.copy_out_file(ostree_initrd_path, extracted_initrd)

        if src_is_aboot:
            # In some case aboot-update adds a bootconfig to the initramfs.
            # This will be re-added when we re-run aboot-update below, but
            # we have to remove the old first to make sure that extending
            # the initramfs with files works.
            run_podman_cmd(
                build_container,
                {"/sysroot": td},
                [
                    "bootconfig",
                    "-d",
                    "/sysroot/initrd",
                ],
                check=True,
                stdout_pipe=None if verbose else subprocess.DEVNULL,
            )

        compression = detect_initrd_compression(extracted_initrd)

        root = Path("root")
        dest_rel = Path("etc/ostree/initramfs-root-binding.key")
        dest_abs = td / root / dest_rel
        dest_abs.parent.mkdir(parents=True)
        shutil.copyfile(pub_key, dest_abs)

        rel_paths = [
            "etc",
            "etc/ostree",
            "etc/ostree/initramfs-root-binding.key",
        ]

        to_append = td / Path("initrd.append")

        create_cpio_archive(to_append, td / root, rel_paths, compression)

        # Pad initrd parts to 4 bytes
        s = os.stat(extracted_initrd)
        padding = (4 - (s.st_size % 4)) % 4

        # Append cpio to initrd
        with open(extracted_initrd, "ab") as f_out:
            for _ in range(padding):
                f_out.write(b"\0")
            with open(to_append, "rb") as f_in:
                shutil.copyfileobj(f_in, f_out)

        with PodmanImageMount(
            src_container, writable=True, commit_image=dest_container
        ) as mount:
            # Copy in the new pubkey and modified initrd
            mount.copy_in_file(pub_key, "etc/ostree/initramfs-root-binding.key")
            mount.copy_in_file(extracted_initrd, ostree_initrd_path)

            # Update aboot.img if aboot is used
            if src_is_aboot:
                run_podman_cmd(
                    build_container,
                    {"/sysroot": mount.mount_path},
                    [
                        "aboot-update",
                        "-p",
                        "-r",
                        "/sysroot",
                        kdir,
                    ],
                    check=True,
                    stdout_pipe=None if verbose else subprocess.DEVNULL,
                )

            # Hardlink updated initramfs in /usr/lib/ostree-boot to the copy
            # in /usr/lib/modules.
            # NOTE: This must run after the above aboot-update, because it can
            # change the initramfs file.
            mount.link_file(
                ostree_initrd_path, f"/usr/lib/modules/{kdir}/initramfs.img"
            )

        return mount.image_id


class ContainerStorageState:
    _cache_nosudo = None
    _cache_sudo = None

    def __init__(self, with_sudo):
        self.with_sudo = with_sudo
        info_json = run_cmd(
            ["podman", "info", "--format", "json"],
            capture_output=True,
            with_sudo=with_sudo,
        )
        info = json.loads(info_json)
        self.graphroot = info["store"]["graphRoot"]
        self.runroot = info["store"]["runRoot"]
        self.driver = info["store"]["graphDriverName"]

    def __str__(self):
        state_parts = [
            f"with_sudo={self.with_sudo}",
            f"graphroot={self.graphroot}",
            f"runroot={self.runroot}",
            f"driver={self.driver}",
        ]
        return f"ContainerStorageState({', '.join(state_parts)})"

    @classmethod
    def query(cls, with_sudo):
        if with_sudo:
            if not cls._cache_sudo:
                cls._cache_sudo = cls(with_sudo)
            return cls._cache_sudo
        else:
            if not cls._cache_nosudo:
                cls._cache_nosudo = cls(with_sudo)
            return cls._cache_nosudo


class ContainerState:
    _cache = None

    def __init__(self):
        self.in_container = False
        self.in_rootless_container = False

        p = Path("/run/.containerenv")
        if p.exists():
            self.in_container = True
            with p.open("r") as f:
                for line in f.read().splitlines():
                    if line == "rootless=1":
                        self.in_rootless_container = True
                        break

    def __str__(self):
        state_parts = [
            f"in_container={self.in_container}",
            f"in_rootless_container={self.in_rootless_container}",
        ]
        return f"ContainerState({', '.join(state_parts)})"

    @classmethod
    def query(cls):
        if not cls._cache:
            cls._cache = cls()
        return cls._cache
