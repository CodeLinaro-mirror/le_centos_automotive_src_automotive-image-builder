"""AIB Exceptions module"""


class AIBException(Exception):
    pass


class InvalidOption(AIBException):
    def __init__(self, option, value):
        self.option = option
        self.value = value

    def __str__(self):
        return (
            f"Invalid value passed to {self.option}: '{self.value}': "
            "should be key=value"
        )


class MissingSection(AIBException):
    def __init__(self, section):
        self.section = section

    def __str__(self):
        return f"No {self.section} section in manifest"


class DefineFileError(AIBException):
    pass


class ManifestParseError(AIBException):
    def __init__(self, manifest_path, cause=None):
        self.manifest = manifest_path
        self.cause = cause

    def __str__(self):
        msg = f"Error parsing {self.manifest}"
        if self.cause:
            msg += f": {self.cause}"
        return msg


class SimpleManifestParseError(AIBException):
    def __init__(self, manifest_path, errors):
        self.manifest = manifest_path
        self.errors = errors

    def __str__(self):
        return f"Error parsing {self.manifest}:\n " + "\n ".join(
            e.message for e in self.errors
        )


class UnsupportedExport(AIBException):
    def __init__(self, export):
        self.export = export

    def __str__(self):
        return f"Unsupported export '{self.export}'"


class InvalidMountSize(AIBException):
    def __init__(self, mountpoint):
        self.mountpoint = mountpoint

    def __str__(self):
        return f"{self.mountpoint} can't be larger than image"


class InvalidMountRelSize(AIBException):
    def __init__(self, mountpoint):
        self.mountpoint = mountpoint

    def __str__(self):
        return f"Invalid relative size for {self.mountpoint}, must be between 0 and 1"


class NoMatchingFilesError(AIBException):
    def __init__(self, glob_pattern):
        self.glob_pattern = glob_pattern

    def __str__(self):
        return f"No files matched glob pattern: {self.glob_pattern}"


class TooManyFilesError(AIBException):
    def __init__(self, glob_pattern, matched_count, max_files):
        self.glob_pattern = glob_pattern
        self.matched_count = matched_count
        self.max_files = max_files

    def __str__(self):
        return (
            f"Glob pattern '{self.glob_pattern}' matched {self.matched_count} files, "
            f"but max_files limit is {self.max_files}. Consider using more specific "
            f"patterns or increase max_files if needed."
        )


class MissingLogFile(AIBException):
    def __str__(self):
        return "Log file must be specified when progress monitoring is enabled"


class InvalidTopLevelPath(AIBException):
    def __init__(self, path, allowed_dirs, disallowed_paths, operation_type):
        self.path = path
        self.allowed_dirs = allowed_dirs
        self.disallowed_paths = disallowed_paths
        self.operation_type = operation_type

    def __str__(self):
        return (
            f"Path '{self.path}' is not allowed for {self.operation_type}. "
            f"Files and directories must be under one of: {', '.join(self.allowed_dirs)}, "
            f"but not under {', '.join(self.disallowed_paths)}"
        )


class ContainerNotFound(AIBException):
    """Raised when a container image is not found in the local container store."""

    def __init__(self, container_name):
        self.container_name = container_name

    def __str__(self):
        return (
            f"Source bootc image '{self.container_name}' isn't in local container store"
        )


class BuildContainerNotFound(AIBException):
    """Raised when the build container is not found in the local container store."""

    def __init__(self, build_container, distro):
        self.build_container = build_container
        self.distro = distro

    def __str__(self):
        return (
            f"Build container {self.build_container} isn't in local container store\n"
            f"Either specify another one with --build-container, or create it using:\n"
            f"  aib build-builder --distro {self.distro}"
        )


class BootcImageBuilderFailed(AIBException):
    """Raised when bootc-image-builder fails to create an image."""

    def __str__(self):
        return "bootc-image-builder failed to create the image"


class IncompatibleOptions(AIBException):
    """Raised when incompatible command-line options are used together."""

    def __init__(self, option1, option2, reason=None):
        self.option1 = option1
        self.option2 = option2
        self.reason = reason

    def __str__(self):
        msg = f"{self.option1} is incompatible with {self.option2}"
        if self.reason:
            msg += f": {self.reason}"
        return msg


class InvalidBuildDir(AIBException):
    """Raised when build directory is required but not specified."""

    def __str__(self):
        return "No build dir specified, refusing to download to temporary directory"


class UnknownSignatureType(AIBException):
    """Raised when an unknown signature type is encountered."""

    def __init__(self, sig_type):
        self.sig_type = sig_type

    def __str__(self):
        return f"Unknown signature type {self.sig_type}"


class PodmanCommandFailed(AIBException):
    """Raised when a podman command fails."""

    def __init__(self, command, error_message):
        self.command = command
        self.error_message = error_message

    def __str__(self):
        msg = f"Failed to run '{self.command}'"
        if self.error_message:
            msg += f": {self.error_message}"
        return msg


class UnsupportedImageType(AIBException):
    """Raised when an unsupported disk image type is requested."""

    def __init__(self, image_type):
        self.image_type = image_type

    def __str__(self):
        return f"Unknown bootc-image-builder type {self.image_type}"


class InitramfsNotFound(AIBException):
    """Raised when initramfs cannot be found in a bootc image."""

    def __init__(self, container_name):
        self.container_name = container_name

    def __str__(self):
        return f"Can't find initramfs in bootc image '{self.container_name}'"
