import argparse
import base64
import errno
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from enum import Enum
from pathlib import Path
from typing import List, Optional


def extract_comment_header(file):
    lines = []
    for line in file:
        line = line.strip()
        if not line.startswith("#"):
            break
        lines.append(line[1:])

    # Unindent
    min_indent = -1
    for line in lines:
        indent = 0
        for c in line:
            if c == " ":
                indent = indent + 1
            else:
                if min_indent < 0:
                    min_indent = indent
                else:
                    min_indent = min(indent, min_indent)
                break

    if min_indent > 0:
        for i in range(len(lines)):
            lines[i] = lines[i][min_indent:]

    # Remove trailing empty lines
    while len(lines) > 0 and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


def get_osbuild_major_version(runner, use_container):
    osbuild_version = runner.run_as_user(
        ["/usr/bin/osbuild", "--version"],
        capture_output=True,
    )
    osbuild_major_version = osbuild_version.split()[-1].split(".")[0]

    return int(osbuild_major_version)


def detect_initrd_compression(path):
    with open(path, "rb") as f:
        head = f.read(16)

    def u32_le(b):
        return int.from_bytes(b[:4], "little") if len(b) >= 4 else -1

    magic32 = u32_le(head)

    # LZ4 family
    if magic32 == 0x184D2204:  # 04 22 4D 18
        return "lz4"  # modern frame
    if magic32 == 0x184C2102:  # 02 21 4C 18
        return "lz4-legacy"
    if 0x184D2A50 <= magic32 <= 0x184D2A5F:  # P* M 18 .. P/*M18
        return "lz4-skippable"

    # Other common ones
    if head.startswith(b"\x1f\x8b"):
        return "gzip"
    if head.startswith(b"\xfd\x37\x7a\x58\x5a\x00"):
        return "xz"
    if head.startswith(b"\x28\xb5\x2f\xfd"):
        return "zstd"
    if head.startswith(b"BZh"):
        return "bzip2"

    # Raw/uncompressed newc cpio (ASCII)
    if head.startswith(b"070701") or head.startswith(b"070702"):
        return "cpio"

    # lzo/lzop (less common for initramfs, but seen)
    if head.startswith(b"\x89LZO\x00\x0d\x0a\x1a\x0a"):
        return "lzo"

    return "unknown"


def initrd_compressor_for(kind):
    if kind == "gzip":
        return ["gzip", "-c"]
    if kind == "xz":
        return ["xz", "-C", "crc32", "-z", "-c"]
    if kind == "zstd":
        return ["zstd", "-q", "-c"]
    if kind == "lz4":
        return ["lz4", "-9", "-c"]  # modern
    if kind == "lz4-legacy":
        return ["lz4", "-l", "-9", "-c"]  # legacy: note the -l
    if kind == "bzip2":
        return ["bzip2", "-c"]
    if kind == "cpio":
        return []  # no compression; append raw cpio
    if kind == "lzo":
        return ["lzop", "-c"]
    raise RuntimeError(f"Unsupported/unknown compression: {kind}")


def create_cpio_archive(dest, basedir, files, compression):
    # Start up cpio
    cpio_cmd = ["cpio", "--null", "-o", "-H", "newc", "--owner", "0:0"]
    try:
        cpio_proc = subprocess.Popen(
            cpio_cmd,
            cwd=basedir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise RuntimeError("cpio not found in PATH")

    # Stream files to cpio, and then close stdin
    assert cpio_proc.stdin is not None
    cpio_proc.stdin.write(b"\x00".join(p.encode() for p in files) + b"\x00")
    cpio_proc.stdin.close()

    comp_cmd = initrd_compressor_for(compression)
    comp_proc = None
    if comp_cmd:
        try:
            comp_proc = subprocess.Popen(
                comp_cmd,
                stdin=cpio_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as e:
            cpio_proc.kill()
            raise RuntimeError(
                f"compressor missing for {compression}: {comp_cmd[0]}"
            ) from e

        cpio_proc.stdout.close()  # Owned by compressor now
        pipe_stdout = comp_proc.stdout
    else:
        pipe_stdout = cpio_proc.stdout

    # Write pipeline output to dest
    with open(dest, "wb") as out:
        shutil.copyfileobj(pipe_stdout, out, length=1024 * 1024)
    pipe_stdout.close()

    comp_rc = 0
    if comp_proc:
        comp_stdout, comp_stderr = comp_proc.communicate()
        comp_rc = comp_proc.returncode

    # Note: We can't user cpio_proc.communicate() here because we closed stdin
    cpio_rc = cpio_proc.wait()
    cpio_stderr = cpio_proc.stderr.read().decode(errors="ignore")

    if cpio_rc != 0:
        raise RuntimeError(f"cpio failed (rc={cpio_rc}): {cpio_stderr}")

    if comp_rc != 0:
        raise RuntimeError(f"{' '.join(comp_cmd)} failed (rc={comp_rc}): {comp_stderr}")


def openssl_stdout(*args, passargs=None):
    args = list(args)
    if passargs:
        args = args + ["-passin", passargs]
    res = subprocess.run(
        ["openssl"] + args, stdout=subprocess.PIPE, input=None, check=True
    )
    return res.stdout


def read_public_key(pemfile, passargs=None):
    # Extract the public parts from key (last 32 byte in PEM file)
    pubkey = openssl_stdout(
        "pkey", "-outform", "DER", "-pubout", "-in", pemfile, passargs=passargs
    )[-32:]

    # Ostree stores keys in base64
    pubkey_b64 = base64.b64encode(pubkey).decode("utf8")

    return pubkey_b64


def read_keys(pemfile, passargs=None):
    # Extract the seed/public parts from generated key (last 32 byte in PEM file)
    pubkey = openssl_stdout(
        "pkey", "-outform", "DER", "-pubout", "-in", pemfile, passargs=passargs
    )[-32:]
    seed = openssl_stdout("pkey", "-outform", "DER", "-in", pemfile, passargs=passargs)[
        -32:
    ]

    # Private key is seed and public key joined
    seckey = seed + pubkey

    # Ostree stores keys in base64
    pubkey_b64 = base64.b64encode(pubkey).decode("utf8")
    seckey_b64 = base64.b64encode(seckey).decode("utf8")

    return (pubkey_b64, seckey_b64)


# Generates an (unencrypted) PEM format ed25519 private key at path
def generate_keys():
    with tempfile.TemporaryDirectory() as tmpdir:
        keypath = os.path.join(tmpdir, "key")
        cmd = [
            "openssl",
            "genpkey",
            "-algorithm",
            "ed25519",
            "-outform",
            "PEM",
            "-out",
            keypath,
        ]
        subprocess.run(cmd, encoding="utf8", stdout=sys.stderr, input=None, check=True)
        return read_keys(keypath)


def rm_rf(path):
    try:
        if os.path.isfile(path) or os.path.islink(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
    except FileNotFoundError:
        pass


def get_current_mounts():
    """Read and parse /proc/mounts to get list of all mount points.

    Returns a list of mount point paths with escape sequences decoded.
    """
    mountpoints = []
    try:
        with open("/proc/mounts", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    mount_point = parts[1].replace("\\040", " ")
                    mountpoints.append(mount_point)
    except (OSError, IOError):
        pass
    return mountpoints


def find_mountpoints_under(path):
    """Find all mountpoints under the given path.

    Returns a list of mount points sorted by depth (deepest first),
    so they can be unmounted in the correct order.
    """
    try:
        path_str = str(Path(path).resolve())
    except FileNotFoundError:
        return []

    all_mounts = get_current_mounts()
    mountpoints = [
        mp for mp in all_mounts if mp.startswith(path_str + "/") or mp == path_str
    ]

    # Sort in reverse order (deepest first) to unmount child mounts before parents
    mountpoints.sort(reverse=True)
    return mountpoints


# This is compatible with tempdir.TemporaryDirectory, but falls back to sudo rm -rf on permission errors
class SudoTemporaryDirectory:
    def __init__(self, suffix=None, prefix=None, dir=None, use_sudo_fallback=True):
        self._path = Path(tempfile.mkdtemp(suffix=suffix, prefix=prefix, dir=dir))
        self.name = str(self._path)
        self._keep_once = False
        self._use_sudo = use_sudo_fallback
        # Remember the base directory for safety checks
        self._base = (
            Path(dir).resolve() if dir else Path(tempfile.gettempdir()).resolve()
        )
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._keep_once:
            self._keep_once = False
            return
        self.cleanup()

    def detach(self):
        """Skip cleanup at the end of the *current* with-block only."""
        self._keep_once = True
        return self

    # Some safety checks:
    def _is_safe_to_delete(self, path):
        try:
            rp = path.resolve()
        except FileNotFoundError:
            return True

        if rp == Path("/") or str(rp) == "":
            return False

        if not rp.is_dir():
            return False

        try:
            rp.relative_to(self._base)
        except ValueError:
            # Not under base dir
            return False

        # Require minimum length to avoid deleting very short critical paths
        return len(str(rp)) > len(str(self._base)) + 3

    def _unmount_subdirs(self, path):
        """Find and unmount any mountpoints under the given directory."""
        mountpoints = find_mountpoints_under(path)

        for mount_point in mountpoints:
            try:
                if self._use_sudo and os.getuid() != 0:
                    subprocess.run(
                        ["sudo", "umount", mount_point],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    subprocess.run(
                        ["umount", mount_point],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            except Exception:
                pass

    def cleanup(self):
        if self._closed:
            return
        self._closed = True

        p = self._path
        if not p.exists():
            return

        # Check for and unmount any mountpoints under this directory
        self._unmount_subdirs(p)

        # Try normal deletion first
        try:
            shutil.rmtree(p)
            return
        except (OSError, PermissionError) as e:
            last_err = e

        # Optionally try sudo fallback
        if self._use_sudo and self._is_safe_to_delete(p):
            try:
                subprocess.run(
                    ["sudo", "rm", "-rf", "--", str(p)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            except subprocess.CalledProcessError as e:
                last_err = e

        # If we reach here, cleanup failed
        raise RuntimeError(f"Failed to cleanup temp directory {p!s}") from last_err

    def __str__(self):
        return self.name

    def __fspath__(self):
        return self.name

    def path(self):
        return self._path


def count_trailing_zeros(b: bytes) -> int:
    mv = memoryview(b)
    i = len(mv) - 1
    while i >= 0 and mv[i] == 0:
        i -= 1
    return len(mv) - 1 - i


def truncate_partition_size(src_path: str, start: int, size: int, block_size=4096):
    """
    Remove trailing hole from the size, ensuring that (if we truncate) the end result
    is some even number of block_size.
    """

    with open(src_path, "rb") as src:
        src_fd = src.fileno()
        end = start + size
        pos = start
        last_data_end = None

        while pos < end:
            try:
                data_start = os.lseek(src_fd, pos, os.SEEK_DATA)
            except OSError:
                break

            if data_start >= end:
                break

            try:
                hole_start = os.lseek(src_fd, data_start, os.SEEK_HOLE)
            except OSError:
                hole_start = end

            hole_start = min(hole_start, end)
            last_data_end = hole_start

            if last_data_end >= end:
                break

            pos = hole_start

        if last_data_end is None:
            return 0

        if last_data_end < end:
            new_size = last_data_end - start
            return min(roundup(new_size, block_size), size)

        return size


def roundup(n: int, block: int) -> int:
    return ((n + block - 1) // block) * block


# This extracts part of a file, typically used
# to exctract partitions from a complete image file.
def extract_part_of_file(
    src_path: str,
    dst_path: str,
    start: int,
    size: int,
    chunk_size=1024 * 1024,
):
    total_written = 0
    with open(src_path, "rb") as src, open(dst_path, "wb") as dst:
        src_fd = src.fileno()
        dst_fd = dst.fileno()

        end = start + size
        pos = start

        while pos < end:
            try:
                data_start = os.lseek(src_fd, pos, os.SEEK_DATA)
            except OSError:
                break

            if data_start >= end:
                break

            try:
                hole_start = os.lseek(src_fd, data_start, os.SEEK_HOLE)
            except OSError:
                hole_start = end

            hole_start = min(hole_start, end)

            data_size = hole_start - data_start
            dst_offset = data_start - start

            os.lseek(src_fd, data_start, os.SEEK_SET)
            os.lseek(dst_fd, dst_offset, os.SEEK_SET)

            remaining = data_size
            while remaining > 0:
                to_read = min(chunk_size, remaining)
                data = os.read(src_fd, to_read)
                if not data:
                    break
                os.write(dst_fd, data)
                total_written += len(data)
                remaining -= len(data)

            pos = hole_start

        # Ensure destination file has the correct size, even if it ends with a hole
        if size > 0:
            os.ftruncate(dst_fd, size)

    return total_written


def convert_to_simg(src_path: str, dst_path: str, block_size: int = 4096):
    """
    Convert file to Android sparse image (v1.0).
    Chunks are strictly block-aligned; offsets are implicit via chunk order.
    """
    if block_size < 1024:
        raise ValueError(f"Block size must be larger than 1024, got {block_size}")
    if block_size % 4 != 0:
        raise ValueError(f"Block size must be multiple of 4, got {block_size}")
    if not hasattr(os, "SEEK_DATA") or not hasattr(os, "SEEK_HOLE"):
        raise OSError("SEEK_DATA/SEEK_HOLE not supported by this Python/OS")

    SPARSE_HEADER_MAGIC = 0xED26FF3A
    CHUNK_TYPE_RAW = 0xCAC1
    CHUNK_TYPE_FILL = 0xCAC2
    CHUNK_TYPE_DONT_CARE = 0xCAC3

    file_size = os.path.getsize(src_path)
    total_blocks = (file_size + block_size - 1) // block_size

    def block_has_data(fd, block_idx):
        start = block_idx * block_size
        end = min(start + block_size, file_size)
        if start >= file_size:
            return False  # beyond EOF: treat as hole (but typically no chunks past total_blocks)
        try:
            off = os.lseek(fd, start, os.SEEK_DATA)
            return off < end
        except OSError as e:
            if e.errno in (errno.ENXIO,):  # no more data past 'start'
                return False
            if e.errno in (
                errno.EINVAL,
                errno.ENOTSUP,
                getattr(errno, "EOPNOTSUPP", 95),
            ):
                raise OSError("Filesystem does not support SEEK_DATA/SEEK_HOLE") from e
            raise

    # Collect chunks of blocks with their type (data or hole)
    chunks = []
    with open(src_path, "rb") as src:
        fd = src.fileno()
        i = 0
        while i < total_blocks:
            has_data = block_has_data(fd, i)
            j = i + 1
            while j < total_blocks and block_has_data(fd, j) == has_data:
                j += 1

            chunks.append(("data" if has_data else "hole", i, j - i))
            i = j

    def is_all_zeros(data: memoryview) -> bool:
        for x in data:
            if x:
                return False
        return True

    # Write sparse image directly to destination
    def analyze_block_runs(buf: bytes, block_size: int):
        runs = []
        total_blocks = len(buf) // block_size
        mv = memoryview(buf)

        block_idx = 0
        while block_idx < total_blocks:
            block_start = block_idx * block_size
            block_end = block_start + block_size
            block_data = mv[block_start:block_end]
            is_zero = is_all_zeros(block_data)

            # Find consecutive blocks of same type
            run_length = 1
            while block_idx + run_length < total_blocks:
                next_start = (block_idx + run_length) * block_size
                next_end = next_start + block_size
                next_block = mv[next_start:next_end]
                next_is_zero = is_all_zeros(next_block)

                if next_is_zero == is_zero:
                    run_length += 1
                else:
                    break

            run_end = block_start + run_length * block_size
            run = mv[block_start:run_end]
            runs.append((is_zero, run_length, run))

            block_idx += run_length

        return runs

    chunk_count = 0
    with open(dst_path, "wb") as dst:
        # Write placeholder header (we'll update chunk_count later)
        sparse_header = struct.pack(
            "<IHHHHIIII",
            SPARSE_HEADER_MAGIC,
            1,  # major_version
            0,  # minor_version
            28,  # file_hdr_sz
            12,  # chunk_hdr_sz
            block_size,
            total_blocks,
            0,  # chunk_count - placeholder
            0,  # image_checksum (0 = not provided)
        )
        dst.write(sparse_header)

        with open(src_path, "rb") as src:
            for kind, start_blk, n_blocks in chunks:
                if kind == "hole":
                    chunk_header = struct.pack(
                        "<HHII", CHUNK_TYPE_DONT_CARE, 0, n_blocks, 12
                    )
                    dst.write(chunk_header)
                    chunk_count += 1
                else:
                    # Stream data chunk, detecting zero-filled blocks on the fly
                    src.seek(start_blk * block_size)
                    blocks_remaining = n_blocks
                    read_chunk_size = (
                        32 * 1024
                    )  # Read 32k blocks at a time (128MB with 4K blocks)

                    while blocks_remaining > 0:
                        blocks_to_read = min(read_chunk_size, blocks_remaining)
                        chunk_data = src.read(blocks_to_read * block_size)

                        # Pad if needed
                        if len(chunk_data) < blocks_to_read * block_size:
                            chunk_data += b"\x00" * (
                                blocks_to_read * block_size - len(chunk_data)
                            )

                        for is_zero, run_length, run in analyze_block_runs(
                            chunk_data, block_size
                        ):
                            if is_zero:
                                chunk_header = struct.pack(
                                    "<HHII", CHUNK_TYPE_FILL, 0, run_length, 16
                                )
                                dst.write(chunk_header)
                                dst.write(struct.pack("<I", 0))
                            else:
                                chunk_header = struct.pack(
                                    "<HHII",
                                    CHUNK_TYPE_RAW,
                                    0,
                                    run_length,
                                    12 + len(run),
                                )
                                dst.write(chunk_header)
                                dst.write(run)

                            chunk_count += 1

                        blocks_remaining -= blocks_to_read

        # Seek back and update the header with correct chunk count
        dst.seek(0)
        sparse_header = struct.pack(
            "<IHHHHIIII",
            SPARSE_HEADER_MAGIC,
            1,  # major_version
            0,  # minor_version
            28,  # file_hdr_sz
            12,  # chunk_hdr_sz
            block_size,
            total_blocks,
            chunk_count,
            0,  # image_checksum (0 = not provided)
        )
        dst.write(sparse_header)


class DiskFormat(Enum):
    def __new__(cls, value: str, ext: str, convert: List[str]):
        obj = object.__new__(cls)
        obj._value_ = value
        obj.ext = ext
        obj.convert = convert
        return obj

    RAW = ("raw", ".img", ["mv"])
    QCOW2 = ("qcow2", ".qcow2", ["qemu-img", "convert", "-O", "qcow2"])
    SIMG = ("simg", ".simg", None)  # This uses internal conversion

    @classmethod
    def from_string(cls, s: str) -> "Optional[DiskFormat]":
        if s is None:
            return None
        s = s.lower()
        for member in cls:
            if s == member.value or s == member.name.lower():
                return member
        valid = ", ".join(m.value for m in cls)
        raise argparse.ArgumentTypeError(f"invalid format {s!r}; choose from: {valid}")

    @classmethod
    def from_filename(cls, filename: str) -> "DiskFormat":
        ext = os.path.splitext(filename.lower())[1]
        for member in cls:
            if ext == member.ext:
                return member
        return cls.RAW

    def convert_image(self, runner, src, dest):
        if self.convert:
            runner.run_in_container(self.convert + [src, dest], need_selinux_privs=True)
            if runner.container_needs_root:
                runner.run_as_root(["chown", f"{os.getuid()}:{os.getgid()}", dest])
        else:
            if self == DiskFormat.SIMG:
                convert_to_simg(src, dest)
