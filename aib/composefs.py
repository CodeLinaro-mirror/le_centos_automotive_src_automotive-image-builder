"""Read and patch composefs digests in existing native boot artifacts."""

import os
import re
import struct

from .exceptions import AIBException

UINT32_SIZE = struct.calcsize("<I")

# Android boot image v2 header.
ABOOT_MAGIC = b"ANDROID!"
ABOOT_HEADER_VERSION = 2
ABOOT_HEADER_SIZE = 1660
ABOOT_PAGE_SIZE_OFFSET = 36
ABOOT_HEADER_VERSION_OFFSET = 40
ABOOT_CMDLINE_OFFSET = 64
ABOOT_CMDLINE_SIZE = 512
ABOOT_EXTRA_CMDLINE_OFFSET = 608
ABOOT_EXTRA_CMDLINE_SIZE = 1024
ABOOT_HEADER_SIZE_OFFSET = 1644

# PE/COFF headers.
PE_DOS_MAGIC = b"MZ"
PE_HEADER_POINTER_OFFSET = 60
PE_SIGNATURE = b"PE\0\0"
PE_HEADER_SIZE = 24  # Includes the signature and COFF header.
PE_SECTION_COUNT_OFFSET = 6
PE_OPTIONAL_HEADER_SIZE_OFFSET = 20
PE_SECTION_HEADER = struct.Struct("<8sIIIIIIHHI")
PE_CMDLINE_SECTION = b".cmdline"

COMPOSEFS_DIGEST_HEX_LENGTH = 128
COMPOSEFS_DIGEST_HEX_PATTERN = rf"[0-9a-fA-F]{{{COMPOSEFS_DIGEST_HEX_LENGTH}}}"


class _BootImage:
    def __init__(self, image):
        self.image = image
        self.size = image.seek(0, os.SEEK_END)
        magic = self.read(0, len(ABOOT_MAGIC))
        if magic == ABOOT_MAGIC:
            data, self.regions = self._read_aboot()
        elif magic.startswith(PE_DOS_MAGIC):
            data, self.regions = self._read_uki()
        else:
            raise AIBException("Unsupported native boot image format")

        try:
            self.cmdline = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise AIBException("Boot image command line is not valid UTF-8") from error

    def _read_aboot(self):
        """Return joined command-line bytes and regions excluding each field's NUL/padding."""
        header = self.read(0, ABOOT_HEADER_SIZE)
        version = struct.unpack_from("<I", header, ABOOT_HEADER_VERSION_OFFSET)[0]
        if version != ABOOT_HEADER_VERSION:
            raise AIBException(f"Unsupported Android boot image version: {version}")
        page_size = struct.unpack_from("<I", header, ABOOT_PAGE_SIZE_OFFSET)[0]
        header_size = struct.unpack_from("<I", header, ABOOT_HEADER_SIZE_OFFSET)[0]
        if not ABOOT_HEADER_SIZE <= header_size <= page_size <= self.size:
            raise AIBException("Invalid Android boot image header")

        # Each field is independently NUL-terminated; the image ID separates
        # them on disk. Only text bytes belong in the logical offset mapping.
        parts = []
        regions = []
        for offset, size in (
            (ABOOT_CMDLINE_OFFSET, ABOOT_CMDLINE_SIZE),
            (ABOOT_EXTRA_CMDLINE_OFFSET, ABOOT_EXTRA_CMDLINE_SIZE),
        ):
            part = header[offset : offset + size].split(b"\0", 1)[0]
            if part:
                parts.append(part)
                regions.append((offset, len(part)))
        return b"".join(parts), regions

    def _read_uki(self):
        """Return command-line bytes and their region within the PE section."""
        pe_offset = struct.unpack(
            "<I", self.read(PE_HEADER_POINTER_OFFSET, UINT32_SIZE)
        )[0]
        header = self.read(pe_offset, PE_HEADER_SIZE)
        if not header.startswith(PE_SIGNATURE):
            raise AIBException("Invalid UKI PE signature")
        sections = struct.unpack_from("<H", header, PE_SECTION_COUNT_OFFSET)[0]
        optional_size = struct.unpack_from(
            "<H", header, PE_OPTIONAL_HEADER_SIZE_OFFSET
        )[0]
        table_size = sections * PE_SECTION_HEADER.size
        table_offset = pe_offset + PE_HEADER_SIZE + optional_size
        table_end = table_offset + table_size
        table = self.read(table_offset, table_size)
        cmdline_region = None
        for section in PE_SECTION_HEADER.iter_unpack(table):
            name, virtual_size, _, raw_size, offset, *_ = section
            if raw_size:
                if offset < table_end or offset + raw_size > self.size:
                    raise AIBException("Invalid UKI section bounds")
            if name.rstrip(b"\0") != PE_CMDLINE_SECTION:
                continue
            if cmdline_region is not None or not 0 < virtual_size <= raw_size:
                raise AIBException("Invalid or ambiguous UKI .cmdline section")
            cmdline_region = (offset, virtual_size)
        if cmdline_region is None:
            raise AIBException("UKI has no .cmdline section")
        offset, size = cmdline_region
        data = self.read(offset, size).split(b"\0", 1)[0]
        return data, [(offset, len(data))]

    def read(self, offset, length):
        if offset < 0 or length < 0 or offset + length > self.size:
            raise AIBException("Invalid boot image: truncated header or section")
        self.image.seek(offset)
        return self.image.read(length)

    def patch(self, offset, data):
        """Map logical command-line bytes back to their physical fields."""
        for start, length in self.regions:
            if offset >= length:
                offset -= length
                continue
            part = data[: length - offset]
            self.image.seek(start + offset)
            self.image.write(part)
            data = data[len(part) :]
            if not data:
                return
            offset = 0
        raise AIBException("Digest extends past the boot image command line")


def boot_image_cmdline(path):
    """Read Android boot v2 or UKI command-line bytes without changing the image."""
    with open(path, "rb") as image:
        return _BootImage(image).cmdline


def _split_cmdline(cmdline):
    """Split kernel options, retaining character offsets and original quoting."""
    # Kernel arguments use double quotes; apostrophes and backslashes are
    # literal bytes, not shell quoting/escaping.
    arguments = []
    start = 0
    quoted = False
    for offset, char in enumerate(cmdline):
        if char == '"':
            quoted = not quoted
        elif char in " \t\n\r\v\f" and not quoted:
            if offset > start:
                arguments.append((start, cmdline[start:offset]))
            start = offset + 1
    arguments.append((start, cmdline[start:]))
    return arguments


def _digest_arguments(cmdline):
    """Read the composefs arguments generated by bootc."""
    digests = []
    seen = set()
    policy = None
    for start, argument in _split_cmdline(cmdline):
        key, separator, value = argument.partition("=")
        if key not in ("composefs", "composefs.digest"):
            continue
        insecure = value.startswith("?")
        if policy is not None and policy != insecure:
            raise AIBException("Conflicting composefs integrity policies")
        policy = insecure
        value = value.removeprefix("?")
        if key == "composefs.digest":
            match = re.fullmatch(
                rf"(v[12])-sha512-12:({COMPOSEFS_DIGEST_HEX_PATTERN})", value
            )
            if not separator or match is None:
                raise AIBException(f"Unsupported composefs digest argument: {argument}")
            versions, digest = (match[1],), match[2]
        else:
            if (
                not separator
                or re.fullmatch(COMPOSEFS_DIGEST_HEX_PATTERN, value) is None
            ):
                raise AIBException(f"Invalid composefs digest argument: {argument}")
            # Released bootc versions used the bare spelling for both formats.
            versions, digest = ("v1", "v2"), value
        identity = (key, versions)
        if identity in seen:
            raise AIBException(f"Duplicate composefs digest argument: {argument}")
        seen.add(identity)
        # Bootc puts the digest at the end of the argument.
        end = start + len(argument)
        offset = len(cmdline[: end - COMPOSEFS_DIGEST_HEX_LENGTH].encode("utf-8"))
        digests.append((versions, digest.lower(), offset))
    if not digests:
        raise AIBException("Boot image has no composefs digest on its command line")
    return digests


def composefs_digests(cmdline):
    """Return (acceptable EROFS versions, digest) for each embedded argument."""
    return [(versions, digest) for versions, digest, _ in _digest_arguments(cmdline)]


def patch_boot_image(path, actual):
    """Update only the embedded command-line digest bytes.

    Bare composefs= arguments in AIB's native artifacts designate V2. Accept
    historical V1 digests when unchanged, as bootc does, without rewriting them.
    """
    with open(path, "r+b") as image:
        boot = _BootImage(image)
        patches = []
        for versions, digest, offset in _digest_arguments(boot.cmdline):
            if digest in (actual[v] for v in versions):
                continue
            replacement = actual[versions[-1]]
            if re.fullmatch(COMPOSEFS_DIGEST_HEX_PATTERN, replacement) is None:
                raise AIBException("Invalid replacement composefs digest")
            patches.append((offset, replacement.lower().encode("ascii")))
        if not patches:
            return False
        for offset, data in patches:
            boot.patch(offset, data)
    return True
