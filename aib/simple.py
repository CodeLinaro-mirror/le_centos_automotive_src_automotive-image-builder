#!/usr/bin/env python3

import os
import yaml
import re
import glob
from enum import Enum

import jsonschema

from . import exceptions, log


class ValidatedPathOperation(Enum):
    """Operations that have path validation rules."""

    ADD_FILES = "add_files"
    MAKE_DIRS = "make_dirs"
    ADD_SYMLINKS = "add_symlinks"

    def allowed_dirs(self):
        """Return the list of allowed top-level directories for this operation."""
        if self == ValidatedPathOperation.ADD_FILES:
            return ["/etc/", "/usr/"]
        elif self == ValidatedPathOperation.MAKE_DIRS:
            return ["/etc/", "/usr/", "/var/"]
        elif self == ValidatedPathOperation.ADD_SYMLINKS:
            return ["/etc/", "/usr/", "/var/"]


# Disallowed paths (take precedence over allowed directories)
DISALLOWED_PATHS = [
    "/usr/local/",
]


# Duplicate a dict and drop one key
def without(d, key):
    new_d = d.copy()
    new_d.pop(key)
    return new_d


def parse_size(s: str):
    """Parse a size string into a number.

    Supported suffixes: kB, kiB, MB, MiB, GB, GiB, TB, TiB
    """
    units = [
        (r"^\s*(\d+)\s*kB$", 1000, 1),
        (r"^\s*(\d+)\s*KiB$", 1024, 1),
        (r"^\s*(\d+)\s*MB$", 1000, 2),
        (r"^\s*(\d+)\s*MiB$", 1024, 2),
        (r"^\s*(\d+)\s*GB$", 1000, 3),
        (r"^\s*(\d+)\s*GiB$", 1024, 3),
        (r"^\s*(\d+)\s*TB$", 1000, 4),
        (r"^\s*(\d+)\s*TiB$", 1024, 4),
        (r"^\s*(\d+)$", 1, 1),
    ]

    for pat, base, power in units:
        m = re.fullmatch(pat, s)
        if m:
            if isinstance(base, int):
                return int(m.group(1)) * base**power

    raise TypeError(f"invalid size value: '{s}'")


# Convert a python value to 'true' or 'false'
def json_bool(b):
    if b:
        return "true"
    return "false"


# The manifest we use is always empty.mpp.yml, but due to who the
# osbuil-mpp syntax and evaluation works we need to also generate an
# extra manifest with the included file content. This is shared betwee
# the QM and the Rootfs partition
class ExtraInclude:
    def __init__(self, basedir):
        self.basedir = os.path.abspath(basedir)
        self.content_id = 1
        self.file_content_inputs = {}
        self.file_content_paths = []

    def gen_id(self):
        content_id = self.content_id
        self.content_id = content_id + 1
        return content_id

    def gen_file_input(self, content_id, data):
        mpp_embed = {
            "id": "image_content_id_" + str(content_id),
        }
        if "text" in data:
            mpp_embed["text"] = data["text"]
        if "url" in data:
            mpp_embed["url"] = data["url"]
        if "source_path" in data:
            path = data["source_path"]
            if not os.path.isabs(path):
                path = os.path.normpath(os.path.join(self.basedir, path))
            mpp_embed["path"] = path
        return {
            "type": "org.osbuild.files",
            "origin": "org.osbuild.source",
            "mpp-embed": mpp_embed,
        }

    def gen_file_copy(self, content_id):
        return {
            "from": {
                "mpp-format-string": "input://inlinefile"
                + str(content_id)
                + "/{embedded['image_content_id_"
                + str(content_id)
                + "']}"
            },
            "to": "tree:///image_content_" + str(content_id),
        }

    def gen_file_copy_out(self, content_id, data):
        return {
            "from": "input://extra/image_content_" + str(content_id),
            "to": "tree://" + data["path"],
        }

    def add_file_copy(self, contents, data):
        # Handle glob patterns
        try:
            self._add_glob_files(contents, data)
        except KeyError:
            # Handle single file as before
            self._add_file_to_content(contents, data)

    def _add_glob_files(self, contents, data):
        """Handle glob pattern file copying with support for limiting files.

        Args:
            contents: The contents object to add files to
            data: Dictionary containing:
                - source_glob: The glob pattern to match files
                - path: Destination directory
                - preserve_path: Whether to preserve directory structure (optional)
                - max_files: Maximum number of files to process (default: 1000)
                - allow_empty: Whether to allow empty matches (default: False)

        Raises:
            NoMatchingFilesError: When no files match the glob pattern and allow_empty is False
            TooManyFilesError: When more than max_files are matched
        """
        source_glob = data["source_glob"]
        dest_dir = data["path"]
        preserve_path = data.get("preserve_path", False)
        # Default limit to prevent ARG_MAX issues
        max_files = data.get("max_files", 1000)
        allow_empty = data.get("allow_empty", False)

        try:
            matched_files = self._find_glob_matches(source_glob)
        except exceptions.NoMatchingFilesError:
            if allow_empty:
                contents.make_dirs.append(
                    {"path": dest_dir, "parents": True, "exist_ok": True}
                )
                log.info(
                    "Glob pattern '%s' matched no files, but allow_empty=True, "
                    "so creating destination directory '%s'",
                    source_glob,
                    dest_dir,
                )
                return
            raise

        # Raise error if too many files are matched
        if len(matched_files) > max_files:
            raise exceptions.TooManyFilesError(
                source_glob, len(matched_files), max_files
            )

        for file_path in matched_files:
            dest_path = self._calculate_destination_path(
                file_path, source_glob, dest_dir, preserve_path
            )

            if preserve_path:
                self._ensure_parent_directory(contents, dest_path, dest_dir)

            file_data = {"source_path": file_path, "path": dest_path}
            self._add_file_to_content(contents, file_data)

    def _find_glob_matches(self, source_glob):
        """Find all files matching the glob pattern"""
        # Make the glob pattern relative to basedir if not absolute
        if not os.path.isabs(source_glob):
            glob_pattern = os.path.join(self.basedir, source_glob)
        else:
            glob_pattern = source_glob

        matched_files = [
            f for f in glob.glob(glob_pattern, recursive=True) if os.path.isfile(f)
        ]

        if not matched_files:
            raise exceptions.NoMatchingFilesError(source_glob)

        return matched_files

    def _calculate_destination_path(
        self, file_path, source_glob, dest_dir, preserve_path
    ):
        """Calculate the destination path for a file based on preserve_path setting"""
        if not preserve_path:
            # Flatten: just use the filename
            return os.path.join(dest_dir, os.path.basename(file_path))

        # Preserve directory structure
        if os.path.isabs(source_glob):
            return self._calculate_absolute_glob_dest_path(
                file_path, source_glob, dest_dir
            )
        else:
            return self._calculate_relative_glob_dest_path(
                file_path, source_glob, dest_dir
            )

    def _calculate_relative_glob_dest_path(self, file_path, source_glob, dest_dir):
        """Calculate destination path for relative glob patterns"""
        if ".." in source_glob:
            return self._handle_parent_directory_glob(file_path, source_glob, dest_dir)
        elif self._is_recursive_glob(source_glob):
            return self._handle_recursive_glob(file_path, source_glob, dest_dir)
        else:
            return self._handle_normal_glob(file_path, dest_dir)

    def _calculate_absolute_glob_dest_path(self, file_path, source_glob, dest_dir):
        """Calculate destination path for absolute glob patterns"""
        glob_pattern = source_glob
        glob_base = os.path.dirname(glob_pattern.split("*")[0].rstrip("/"))
        rel_path = os.path.relpath(file_path, glob_base)
        return os.path.normpath(os.path.join(dest_dir, rel_path))

    def _handle_parent_directory_glob(self, file_path, source_glob, dest_dir):
        """Handle globs with parent directory references like '../aib/**/*.py'"""
        glob_prefix = source_glob.split("*")[0].rstrip("/")
        base_dir = os.path.normpath(os.path.join(self.basedir, glob_prefix))
        rel_path = os.path.relpath(file_path, base_dir)
        return os.path.normpath(os.path.join(dest_dir, rel_path))

    def _handle_recursive_glob(self, file_path, source_glob, dest_dir):
        """Handle recursive globs like 'test-data/**/*' or 'test-data/**/*.py'"""
        if source_glob.endswith("/**/*"):
            glob_prefix = source_glob[:-5]  # Remove '/**/*'
        else:
            # Handle cases like "test-data/**/*.py"
            glob_prefix = source_glob.split("/**/*")[0]

        if glob_prefix:
            base_dir = os.path.normpath(os.path.join(self.basedir, glob_prefix))
            rel_path = os.path.relpath(file_path, base_dir)
        else:
            # No prefix, use basedir
            rel_path = os.path.relpath(file_path, self.basedir)

        return os.path.normpath(os.path.join(dest_dir, rel_path))

    def _handle_normal_glob(self, file_path, dest_dir):
        """Handle normal glob patterns like 'files/*.conf'"""
        rel_path = os.path.relpath(file_path, self.basedir)
        return os.path.normpath(os.path.join(dest_dir, rel_path))

    def _is_recursive_glob(self, source_glob):
        """Check if the glob pattern is recursive (contains /**/)"""
        return source_glob.endswith("/**/*") or "/**/*" in source_glob

    def _ensure_parent_directory(self, contents, dest_path, dest_dir):
        """Ensure parent directories are created when preserving paths"""
        if os.path.dirname(dest_path) == dest_dir:
            return  # No parent directory structure to preserve

        parent_dir = os.path.dirname(dest_path)
        if not parent_dir or parent_dir == "/":
            return  # No valid parent directory

        # Check if this directory is already in make_dirs
        existing_dirs = [
            d.get("path") if isinstance(d, dict) else d for d in contents.make_dirs
        ]

        if parent_dir not in existing_dirs:
            # Add directory to make_dirs if it's not already there
            # Use exist_ok to avoid failures when directory already exists
            contents.make_dirs.append(
                {"path": parent_dir, "parents": True, "exist_ok": True}
            )

    def _add_file_to_content(self, contents, file_data):
        """Add a file to the content processing pipeline"""
        content_id = self.gen_id()
        self.file_content_inputs["inlinefile" + str(content_id)] = self.gen_file_input(
            content_id, file_data
        )
        self.file_content_paths.append(self.gen_file_copy(content_id))
        contents.file_content_copy.append(self.gen_file_copy_out(content_id, file_data))

    def generate(self):
        extra_include_pipelines = []
        file_content_stages = []

        if self.file_content_inputs:
            file_content_stages.append(
                {
                    "type": "org.osbuild.copy",
                    "inputs": self.file_content_inputs,
                    "options": {"paths": self.file_content_paths},
                }
            )

        if file_content_stages:
            extra_include_pipelines.append(
                {"name": "extra-image-content", "stages": file_content_stages}
            )

        return {"version": "2", "pipelines": extra_include_pipelines}


# Both the rootfs and qm partition contents are specified with the same
# syntax, but use slightly different mpp variables, to share this code
# we have one class (Contents) for the rootfs one and override some details
# in the QMContents class.
class Contents:
    def __init__(self, loader, data, extra_include):
        self.loader = loader
        self.extra_include = extra_include

        self.enable_repos = data.get("enable_repos", [])
        self.repos = data.get("repos", [])
        self.rpms = data.get("rpms", [])
        self.containers = data.get("container_images", [])
        self.add_files = data.get("add_files", [])
        self.chown_files = data.get("chown_files", [])
        self.chmod_files = data.get("chmod_files", [])
        self.remove_files = data.get("remove_files", [])
        self.make_dirs = data.get("make_dirs", [])
        self.add_symlinks = data.get("add_symlinks", [])
        self.file_content_copy = []
        self.systemd = data.get("systemd", {})
        self.sbom = data.get("sbom", {})

        self.validate_paths()

    def _validate_path(self, path, operation_type):
        """Check if a single path is under allowed top-level directories."""
        # Get the allowed directories for this operation type
        allowed_dirs = operation_type.allowed_dirs()

        # First check if path is explicitly disallowed
        if any(path.startswith(prefix) for prefix in DISALLOWED_PATHS):
            raise exceptions.InvalidTopLevelPath(
                path, allowed_dirs, DISALLOWED_PATHS, operation_type.value
            )

        # Then check if path is under allowed directories
        if not any(path.startswith(prefix) for prefix in allowed_dirs):
            raise exceptions.InvalidTopLevelPath(
                path, allowed_dirs, DISALLOWED_PATHS, operation_type.value
            )

    def validate_paths(self):
        """Validate that all paths are under allowed top-level directories."""
        # List of (data, path_key, operation_type) tuples to validate
        validations = [
            (self.make_dirs, "path", ValidatedPathOperation.MAKE_DIRS),
            (self.add_files, "path", ValidatedPathOperation.ADD_FILES),
            (self.add_symlinks, "link", ValidatedPathOperation.ADD_SYMLINKS),
        ]

        for data, path_key, operation_type in validations:
            for entry in data:
                self._validate_path(entry.get(path_key, ""), operation_type)

    # Gets key to use for target partition (rootfs/qm)
    def get_key(self, key):
        return key

    # Sets different key depending on target partition
    def set_define(self, key, value):
        key = self.get_key(key)
        self.loader.set(key, value)

    def set_defines(self):
        for file in self.add_files:
            self.extra_include.add_file_copy(self, file)

        self.set_define("simple_copy", self.file_content_copy)

        self.set_define("simple_mkdir", self.make_dirs)

        simple_symlinks = [
            {
                "target": s["target"],
                "link_name": "tree://" + s["link"],
                "symbolic": True,
            }
            for s in self.add_symlinks
        ]
        self.set_define("simple_symlinks", simple_symlinks)

        chmod_files = {f["path"]: without(f, "path") for f in self.chmod_files}
        self.set_define("simple_chmod", chmod_files)

        chown_files = {f["path"]: without(f, "path") for f in self.chown_files}
        self.set_define("simple_chown", chown_files)

        simple_remove = []
        for remove in self.remove_files:
            simple_remove.append(remove["path"])
        self.set_define("simple_remove", simple_remove)

        for r in self.repos:
            url = r["baseurl"]
            r["baseurl"] = url.replace("$arch", self.loader.defines["arch"])

        if "debug" in self.enable_repos:
            self.set_define("simple_add_debug_repos", True)
        if "devel" in self.enable_repos:
            self.set_define("simple_add_devel_repos", True)

        # If we have containers, always add podman rpm
        if self.containers:
            self.rpms.append("podman")

        self.set_define("simple_repos", self.repos)
        self.set_define("simple_rpms", self.rpms)

        self.set_define("simple_containers", self.containers)
        if self.containers:
            self.set_define("use_containers_extra_store", True)

        if self.systemd:
            self.set_define("simple_systemd", self.systemd)

        if self.sbom:
            self.set_define("simple_sbom", self.sbom)


class QMContents(Contents):
    def __init__(self, loader, data, extra_include):
        Contents.__init__(self, loader, data, extra_include)

    def get_key(self, key):
        if key.startswith("use_"):
            return "use_qm_" + key[4:]
        return "qm_" + key

    def set_defines(self):
        Contents.set_defines(self)


def extend_with_default(validator_class):
    validate_properties = validator_class.VALIDATORS["properties"]

    def set_defaults(validator, properties, instance, schema):
        for property, subschema in properties.items():
            if isinstance(subschema, dict) and "default" in subschema:
                instance.setdefault(property, subschema["default"])

        for error in validate_properties(validator, properties, instance, schema):
            yield error

    return jsonschema.validators.extend(
        validator_class,
        {"properties": set_defaults},
    )


class ManifestLoader:
    def __init__(self, defines, policy=None):
        self.aib_basedir = defines["_basedir"]
        self.workdir = defines["_workdir"]
        self.defines = defines
        self.policy = policy

        # Note: Draft7 is what osbuild uses, and is available in rhel9
        base_cls = jsonschema.Draft7Validator
        validator_cls = extend_with_default(base_cls)

        with open(
            os.path.join(self.aib_basedir, "files/manifest_schema.yml"),
            mode="r",
        ) as file:
            self.aib_schema = yaml.load(file, yaml.SafeLoader)
            base_cls.check_schema(self.aib_schema)

        self.validator = validator_cls(self.aib_schema)

    def set(self, key, value):
        if (isinstance(value, list) or isinstance(value, dict)) and len(value) == 0:
            return
        self.defines[key] = value

    def set_from(self, key, src_dict, src_key, default=None):
        if src_key in src_dict:
            self.set(key, src_dict[src_key])
        elif default is not None:
            self.set(key, default)

    def handle_qm(self, qm, extra_include):
        self.set("use_qm", True)
        if "content" in qm:
            qm_content = QMContents(self, qm["content"], extra_include)
            qm_content.set_defines()

        memory_limit = qm.get("memory_limit", {})
        self.set_from("qm_memory_max", memory_limit, "max")
        self.set_from("qm_memory_high", memory_limit, "high")

        self.set_from("qm_cpu_weight", qm, "cpu_weight")
        self.set_from("boot_check_qm_digest", qm, "container_checksum")

    def handle_network(self, network):
        static = network.get("static", None)
        if static is not None:
            self.set("use_static_ip", True)
            self.set_from("static_ip", static, "ip")
            ip_prefixlen = static.get("ip_prefixlen", None)
            if ip_prefixlen:
                self.set("static_ip_prefixlen", str(ip_prefixlen))
            self.set_from("static_gw", static, "gateway")
            self.set_from("static_dns", static, "dns")
            self.set_from("static_ip_iface", static, "iface")
            if "load_module" in static:
                self.set("static_ip_modules", [static["load_module"]])

    def handle_auth(self, auth):
        self.set_from("root_password", auth, "root_password")
        self.set_from("root_ssh_keys", auth, "root_ssh_keys")
        self.set_from("simple_sshd_config", auth, "sshd_config")
        self.set_from("simple_groups", auth, "groups")
        self.set_from("simple_users", auth, "users")

    def handle_kernel(self, kernel):
        self.set_from("kernel_package", kernel, "kernel_package")
        self.set_from("kernel_version", kernel, "kernel_version")
        self.set_from("kernel_loglevel", kernel, "loglevel")
        self.set_from("use_debug", kernel, "debug_logging")
        self.set_from("simple_kernel_opts", kernel, "cmdline")
        self.set_from("denylist_modules", kernel, "remove_modules")

    def handle_image(self, image):
        image_size = image.get("image_size")
        if image_size:
            image_size = parse_size(image_size)
            self.set("image_size", str(image_size))
        partitions = image.get("partitions", {})
        for k in partitions:
            part = partitions[k]
            if k in ["var", "var_qm"]:
                if k == "var":
                    prefix = ""
                    mountpoint = "/var"
                else:
                    prefix = "qm_"
                    mountpoint = "/var/qm"

                if "size" in part:
                    var_size = part.get("size")
                    var_size = parse_size(var_size)
                    if image_size and var_size >= image_size:
                        raise exceptions.InvalidMountSize(mountpoint)
                    self.set(prefix + "varpart_size", int(var_size / 512))
                elif "relative_size" in part:
                    rel_var_size = part.get("relative_size")
                    if rel_var_size >= 1:
                        raise exceptions.InvalidMountRelSize(mountpoint)
                    self.set(prefix + "varpart_relative_size", rel_var_size)
                elif "external" in part and part["external"]:
                    self.set(prefix + "varpart_size", -1)

                if "uuid" in part:
                    self.set(prefix + "varpart_uuid", part.get("uuid"))

            elif k == "root":
                self.set_from("grow_rootfs", part, "grow")

            else:  # Non /var or root
                if "size" in part:
                    part_size = parse_size(part["size"])
                    self.set(k + "part_size", int(part_size / 512))
        cg_memory_min_value = parse_size(image.get("cg_memory_min", "64MiB"))
        if cg_memory_min_value == 0:
            raise exceptions.AIBException("cg_memory_min must be > 0")
        self.set("cg_memory_min", cg_memory_min_value)
        self.set_from("enable_oom_protection", image, "enable_oom_protection")
        self.set_from("enable_reclaim_protection", image, "enable_reclaim_protection")
        self.set_from("hostname", image, "hostname")
        self.set_from("ostree_ref", image, "ostree_ref")
        self.set_from("use_composefs_signed", image, "sealed")
        self.set_from("selinux_mode", image, "selinux_mode")
        self.set_from("selinux_policy", image, "selinux_policy")
        bools = image.get("selinux_booleans", {})
        if len(bools) > 0:
            self.set(
                "selinux_booleans", [f"{k}={json_bool(v)}" for (k, v) in bools.items()]
            )

    def handle_sysboot_checks(self, content, image):

        # System boot checks building on
        # https://gitlab.com/CentOS/automotive/src/sysboot
        #
        # For each boot_checks entry a respective systemd drop-in
        # directory for the instance (defined by name) is created,
        # the drop-in file with the command placed and the systemd
        # template service instance enabled
        boot_checks = image.get("boot_checks", {})
        if not boot_checks:
            return

        commands = boot_checks.get("commands", [])
        systemd_units = boot_checks.get("systemd", [])

        for boot_check in commands:
            boot_check_name = boot_check.get("name", "")
            boot_check_cmd = boot_check.get("cmd", "")

            service_name = f"sysboot-check@{boot_check_name}.service"
            dropin_dir = f"/usr/lib/systemd/system/{service_name}.d"
            dropin_file = f"{dropin_dir}/{boot_check_name}.conf"

            content.make_dirs.append(
                {
                    "path": dropin_dir,
                    "mode": 0o755,
                    "parents": True,
                    "exist_ok": True,
                }
            )
            content.add_files.append(
                {"path": dropin_file, "text": f"[Service]\nExecStart={boot_check_cmd}"}
            )

            if "enabled_services" not in content.systemd:
                content.systemd["enabled_services"] = []
            content.systemd["enabled_services"].append(service_name)

        for unit in systemd_units:
            dropin_dir = f"/usr/lib/systemd/system/{unit}.d"
            dropin_file = f"{dropin_dir}/sysboot.conf"

            content.make_dirs.append(
                {
                    "path": dropin_dir,
                    "mode": 0o755,
                    "parents": True,
                    "exist_ok": True,
                }
            )
            content.add_symlinks.append(
                {
                    "link": dropin_file,
                    "target": "/usr/share/sysboot/service.d/sysboot.conf",
                }
            )

        if commands or systemd_units:
            content.systemd["enabled_services"].append("sysboot-health.target")
            content.set_define("system_boot_check", True)

    def handle_experimental(self, experimental):
        internal_defines = experimental.get("internal_defines", {})
        for k in internal_defines:
            self.set(k, internal_defines[k])

    def load(self, path, manifest_basedir):
        with open(path, mode="r") as f:
            try:
                manifest = yaml.safe_load(f)
            except yaml.YAMLError as exc:
                raise exceptions.ManifestParseError(manifest_basedir) from exc

        self._load(manifest, path, manifest_basedir)

    def _load(self, manifest, path, manifest_basedir):
        errors = sorted(self.validator.iter_errors(manifest), key=lambda e: e.path)
        if errors:
            raise exceptions.SimpleManifestParseError(path, errors)
        # Policy-based manifest validation
        if self.policy:
            policy_errors = self.policy.validate_manifest(manifest)
            if policy_errors:
                raise exceptions.AIBException(
                    "Manifest policy validation failed:\n" + "\n".join(policy_errors)
                )

        # Extra include snippet for content, shared between contents
        extra_include = ExtraInclude(manifest_basedir)

        self.set_from("name", manifest, "name")
        self.set_from("version", manifest, "version")
        self.set_from("target", manifest, "target")

        content = Contents(self, manifest.get("content", {}), extra_include)

        # Handling the sysboot check before the calling of set_defines()
        # since handling the sysboot check entries adds additional, required
        # directories and files to the content
        image = manifest.get("image", {})
        self.handle_sysboot_checks(content, image)

        content.set_defines()

        if "qm" in manifest:
            self.handle_qm(manifest["qm"], extra_include)

        self.handle_network(manifest.get("network", {}))
        self.handle_auth(manifest.get("auth", {}))
        self.handle_kernel(manifest.get("kernel", {}))
        self.handle_image(image)
        self.handle_experimental(manifest.get("experimental", {}))

        # Write out extra_include mpp file for file content
        extra_include_path = os.path.join(self.workdir, "extra-include.ipp.yml")
        with open(extra_include_path, "w") as f:
            yaml.dump(extra_include.generate(), f, sort_keys=False)
        self.set("simple_import", extra_include_path)
