"""Shared filesystem and tmpfiles helpers for image postprocessing."""

from collections import deque
import errno
import os
from pathlib import Path
import re
import stat
import tempfile

TMPFILES_FIELD = re.compile(
    r"""(?:[^\s"'\\]|\\.|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')+"""
)
TMPFILES_ESCAPE = re.compile(
    r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|[0-7]{3}|.)"
)
QM_VAR_TMPFILES = "usr/lib/qm/tmpfiles.d/var.conf"


def resolve_in_root(root, path, follow_final=True):
    """Resolve image symlinks, interpreting absolute targets inside the image."""
    pending = deque(Path(path).parts)
    resolved = []
    symlinks = 0
    while pending:
        part = pending.popleft()
        if part in ("/", "//", "."):
            continue
        if part == "..":
            if resolved:
                resolved.pop()
            continue
        candidate = root.joinpath(*resolved, part)
        if (pending or follow_final) and candidate.is_symlink():
            symlinks += 1
            if symlinks > 40:
                raise OSError(errno.ELOOP, "Too many symbolic links", str(path))
            target = candidate.readlink()
            if target.is_absolute():
                resolved.clear()
            pending.extendleft(reversed(target.parts))
        else:
            resolved.append(part)
    return root.joinpath(*resolved)


def ensure_file_contents(path, contents, mode=None):
    """Replace text atomically, preserving ownership and non-SELinux xattrs."""
    metadata = path.stat() if path.exists() else None
    if metadata and path.read_text(errors="surrogateescape") == contents:
        if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
            path.chmod(mode)
        return
    with tempfile.NamedTemporaryFile(
        mode="w", errors="surrogateescape", dir=path.parent, delete=False
    ) as stream:
        try:
            if metadata:
                os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
                for attribute in os.listxattr(path):
                    # Native composefs derives labels from the target policy.
                    # Copying host SELinux labels may be forbidden in userns.
                    if attribute == "security.selinux":
                        continue
                    os.setxattr(
                        stream.fileno(), attribute, os.getxattr(path, attribute)
                    )
            os.fchmod(
                stream.fileno(),
                (
                    mode
                    if mode is not None
                    else stat.S_IMODE(metadata.st_mode) if metadata else 0o644
                ),
            )
            stream.write(contents)
            stream.close()
            os.replace(stream.name, path)
        finally:
            Path(stream.name).unlink(missing_ok=True)


def tmpfiles_unescape(value):
    escapes = {
        "a": "\a",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
        "s": " ",
        "\\": "\\",
        '"': '"',
        "'": "'",
    }
    result = bytearray()
    end = 0
    for match in TMPFILES_ESCAPE.finditer(value):
        result.extend(os.fsencode(value[end : match.start()]))
        escaped = match[1]
        if escaped.startswith("x"):
            result.append(int(escaped[1:], 16))
        elif escaped.startswith(("u", "U")):
            result.extend(chr(int(escaped[1:], 16)).encode("utf-8"))
        elif len(escaped) == 3 and escaped.isdigit():
            result.append(int(escaped, 8))
        elif escaped in escapes:
            result.extend(os.fsencode(escapes[escaped]))
        else:
            raise ValueError(f"Unsupported tmpfiles escape: {match[0]}")
        end = match.end()
    result.extend(os.fsencode(value[end:]))
    return os.fsdecode(bytes(result))


def tmpfiles_fields(line):
    """Read the type and path, retaining C escapes until after unquoting."""
    fields = []
    position = 0
    for _ in range(2):
        while position < len(line) and line[position].isspace():
            position += 1
        match = TMPFILES_FIELD.match(line, position)
        if match is None:
            raise ValueError(f"Invalid tmpfiles rule: {line!r}")
        token = re.sub(
            r"\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)'",
            lambda m: m[1] if m[1] is not None else m[2],
            match[0],
        )
        fields.append(tmpfiles_unescape(token))
        position = match.end()
    return fields


def tmpfiles_escape(value):
    """Quote literal filesystem bytes, including systemd's % specifiers."""
    result = []
    for byte in os.fsencode(value):
        if byte == ord("%"):
            result.append("%%")
        elif chr(byte).isascii() and (chr(byte).isalnum() or chr(byte) in "/._-"):
            result.append(chr(byte))
        else:
            result.append(f"\\x{byte:02x}")
    return "".join(result)


def split_qm_tmpfiles(entries):
    """Defer QM state until after mounting, retaining host paths and owners."""
    host = []
    qm = []
    for line in entries:
        if not line.strip() or line.lstrip().startswith(("#", ";")):
            host.append(line)
            continue
        _, path = tmpfiles_fields(line)
        if path.rstrip("/") == "/var/qm":
            # First create the mountpoint in /var, then apply its ownership
            # and label to the filesystem mounted over it.
            host.append(line)
            qm.append(line)
        elif path.startswith("/var/qm/"):
            qm.append(line)
        else:
            host.append(line)
    return host, qm
