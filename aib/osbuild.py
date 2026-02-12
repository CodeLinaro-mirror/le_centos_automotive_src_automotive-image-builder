#!/usr/bin/env python3

import base64
import os
import json
import yaml

from .utils import (
    get_osbuild_major_version,
)
from .ostree import OSTree
from .simple import ManifestLoader
from . import exceptions
from .utils import (
    SudoTemporaryDirectory,
    truncate_partition_size,
    extract_part_of_file,
)
from .globals import default_target


def parse_define(d, option):
    parts = d.split("=", 1)
    if len(parts) != 2:
        raise exceptions.InvalidOption(option, d)
    k = parts[0]
    yaml_v = parts[1]
    try:
        v = yaml.safe_load(yaml_v)
    except yaml.parser.ParserError as e:
        raise exceptions.InvalidOption(option, yaml_v) from e
    return k, v


def make_embed_path_abs(stage, path):
    for k, v in stage.items():
        try:
            embed_path = v["path"]
        except (KeyError, TypeError):
            if isinstance(v, dict):
                make_embed_path_abs(v, path)
            continue

        if k == "mpp-embed" and not os.path.isabs(embed_path):
            v["path"] = os.path.normpath(
                os.path.join(os.path.abspath(path), embed_path)
            )


def rewrite_manifest(manifest, path):
    pipelines = manifest.get("pipelines")
    if not pipelines:
        raise exceptions.MissingSection("pipelines")

    rootfs = None
    for p in pipelines:
        if p.get("name") == "rootfs":
            rootfs = p
        for stage in p.get("stages", []):
            make_embed_path_abs(stage, path)

    # Also, we need to inject some workarounds in the rootfs stage
    if rootfs and "stages" in rootfs:
        rootfs["stages"] = [
            {"mpp-eval": "init_rootfs_dirs_stage"},
            # See comment in kernel_cmdline_stage variable
            {"mpp-eval": "kernel_cmdline_stage"},
            {"mpp-eval": "init_rootfs_files_stage"},
        ] + rootfs.get("stages", [])


def strip_ext(path):
    return os.path.splitext(os.path.splitext(path)[0])[0]


def validate_policy_args(args, target):
    """Validate build arguments against policy restrictions."""
    if args.policy:
        errors = []

        # Validate manifest type
        errors.extend(
            args.policy.validate_manifest_type(args.simple_manifest is not None)
        )

        # Validate build arguments
        errors.extend(
            args.policy.validate_build_args(args.mode, target, args.distro, args.arch)
        )

        if errors:
            raise exceptions.AIBException(
                "Policy validation failed:\n" + "\n".join(errors)
            )


def create_osbuild_manifest(args, tmpdir, out, runner, storage):
    with open(args.manifest) as f:
        try:
            manifest = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise exceptions.ManifestParseError(args.manifest) from exc

    rewrite_manifest(manifest, os.path.dirname(args.manifest))

    runner.add_volume_for(args.manifest)
    runner.add_volume_for(out)

    defines = {
        "_basedir": args.base_dir,
        "_workdir": tmpdir.name,
        "name": manifest.get("mpp-vars", {}).get(
            "name", strip_ext(os.path.basename(args.manifest))
        ),
        "arch": args.arch,
        "distro_name": args.distro,
        "image_mode": args.mode,
        "osbuild_major_version": get_osbuild_major_version(
            runner, use_container=args.container
        ),
        # This is a leftover for backwards compatibilty:
        "image_type": "ostree" if args.mode == "image" else "regular",
    }

    if args.dump_variables:
        defines["print_variables"] = True

    # Add policy-derived variables
    if args.policy:
        policy = args.policy

        # Add forced variables from policy
        forced_vars = policy.get_forced_variables()
        defines.update(forced_vars)

        # Add denylist variables
        defines["policy_denylist_rpms"] = policy.disallowed_rpms
        defines["policy_denylist_modules"] = policy.disallowed_kernel_modules

        # Add sysctl options
        sysctl_options = []
        for key, value in policy.get_forced_sysctl().items():
            sysctl_options.append({"key": key, "value": value})
        defines["policy_systemctl_options"] = sysctl_options

        # Add SELinux booleans
        selinux_booleans = []
        for key, value in policy.get_forced_selinux_booleans().items():
            bool_str = "true" if value else "false"
            selinux_booleans.append(f"{key}={bool_str}")
        defines["policy_selinux_booleans"] = selinux_booleans

    defines["target"] = default_target
    if args.simple_manifest:
        loader = ManifestLoader(defines, args.policy)

        # Note: This may override the 'target' define
        loader.load(args.simple_manifest, os.path.dirname(args.simple_manifest))
    if args.target:
        defines["target"] = args.target

    validate_policy_args(args, defines["target"])

    if args.ostree_repo:
        runner.add_volume_for(args.ostree_repo)

        ostree = OSTree(args.ostree_repo, runner)
        revs = {}
        for ref in ostree.refs():
            rev = ostree.rev_parse(ref)
            revs[ref] = rev
        defines["ostree_parent_refs"] = revs

    for d in args.define:
        k, v = parse_define(d, "--define")
        defines[k] = v

    for df in args.define_file:
        try:
            with open(df) as f:
                file_defines = yaml.safe_load(f)
            if not isinstance(file_defines, dict):
                raise exceptions.DefineFileError("Define file must be yaml dict")
            for k, v in file_defines.items():
                defines[k] = v
        except yaml.parser.ParserError as e:
            raise exceptions.DefineFileError(
                f"Invalid yaml define file '{df}': {e}"
            ) from e

    for d in args.extend_define:
        k, v = parse_define(d, "--extend-define")
        if not isinstance(v, list):
            v = [v]
        if k not in defines:
            defines[k] = []
        defines[k].extend(v)

    if args.local_repo:
        defines["local_repo"] = os.path.abspath(args.local_repo)

    cmdline = [os.path.join(args.base_dir, "mpp/aib-osbuild-mpp")]
    for inc in args.include_dirs:
        cmdline += ["-I", inc]

    for k in sorted(defines.keys()):
        v = defines[k]
        cmdline += ["-D", f"{k}={json.dumps(v)}"]

    if args.cache:
        cmdline += ["--cache", args.cache]
    else:
        # By default we use an isolated dnf cache to avoid stale caches
        cmdline += ["--cache", os.path.join(tmpdir, "dnf-cache")]

    variables_manifest = {
        "version": manifest["version"],
        "mpp-vars": manifest.get("mpp-vars", {}),
    }

    rewritten_manifest_path = os.path.join(tmpdir, "manifest-variables.ipp.yml")
    with open(rewritten_manifest_path, "w") as f:
        yaml.dump(variables_manifest, f, sort_keys=False)

    del manifest["mpp-vars"]

    rewritten_manifest_path = os.path.join(tmpdir, "manifest.ipp.yml")
    with open(rewritten_manifest_path, "w") as f:
        yaml.dump(manifest, f, sort_keys=False)

    cmdline += [os.path.join(args.base_dir, "include/main.ipp.yml"), out]

    # mpp-osbuild only looks in the default (host or user depending on uid) container store
    # so we need to use env-vars to override it.
    volumes = {}
    if storage:
        cmdline = [
            "env",
            f"CONTAINERS_STORAGE_CONF={storage.get_config_path()}",
        ] + cmdline
        volumes[storage.storage] = storage.storage

    runner.run_in_container(cmdline, extra_volumes=volumes, need_selinux_privs=True)


def extract_rpmlist_json(osbuild_manifest):
    with open(osbuild_manifest) as f:
        d = json.load(f)

    pipelines = d["pipelines"]
    rpmlist = None
    for p in pipelines:
        if p.get("name") == "rpmlist":
            rpmlist = p
            break
    inline_digest = list(rpmlist["stages"][0]["inputs"]["inlinefile"]["references"])[0]

    inline_items = d["sources"]["org.osbuild.inline"]["items"]
    data_b64 = inline_items[inline_digest]["data"]
    return base64.b64decode(data_b64).decode("utf8")


def run_osbuild(args, tmpdir, runner, exports, in_vm=None, storage=None):
    osbuild_manifest = os.path.join(tmpdir, "osbuild.json")
    if args.osbuild_manifest:
        osbuild_manifest = args.osbuild_manifest

    create_osbuild_manifest(args, tmpdir, osbuild_manifest, runner, storage=storage)

    builddir = tmpdir
    if args.build_dir:
        builddir = args.build_dir
        os.makedirs(builddir, exist_ok=True)
    runner.add_volume(builddir)
    runner.add_volume("/dev")

    cmdline = ["osbuild"]

    with SudoTemporaryDirectory(prefix="image_output--", dir=builddir) as outputdir:
        cmdline += [
            "--store",
            os.path.join(builddir, "osbuild_store"),
            "--output-directory",
            outputdir.name,
        ]

        if args.build_dir:
            # Cache stuff between builds
            cmdline += [
                "--checkpoint",
                "build",
                "--checkpoint",
                "extra-tree-content",
                "--checkpoint",
                "qm_rootfs_base",
                "--checkpoint",
                "qm_rootfs",
                "--checkpoint",
                "data",
                "--checkpoint",
                "rootfs",
            ]

        if args.cache_max_size:
            cmdline += ["--cache-max-size=" + args.cache_max_size]

        if args.progress:
            # Add JSONSeqMonitor for progress monitoring
            cmdline += ["--monitor", "JSONSeqMonitor"]

        for exp in exports:
            cmdline += ["--export", exp]

        if in_vm:
            for pipeline in in_vm:
                cmdline += ["--in-vm", pipeline]

        cmdline += [osbuild_manifest]

        volumes = {}
        if storage:
            cmdline = [
                "env",
                f"CONTAINERS_STORAGE_CONF={storage.get_config_path()}",
            ] + cmdline
            volumes[storage.storage] = storage.storage

        runner.run_in_container(
            cmdline,
            need_osbuild_privs=True,
            progress=args.progress,
            verbose=args.verbose,
            log_file=args.log_file(tmpdir),
            extra_volumes=volumes,
        )

        return outputdir.detach()


def partition_is_safe_to_truncate(p):
    name = p.get("name")
    if name:
        prefixes = ["boot_", "vbmeta_", "ukiboot"]
        for p in prefixes:
            if name.startswith(p):
                return True
    return False


def export_disk_image_file(runner, args, tmpdir, image_file, out, fmt):
    runner.add_volume_for(out)
    if args.separate_partitions:
        runner.rm_rf(out)
        os.mkdir(out)

        disk_json = runner.run_in_container(
            ["sfdisk", "--json", image_file], capture_output=True
        )
        parts = json.loads(disk_json)
        for idx, p in enumerate(parts["partitiontable"]["partitions"]):
            start = int(p["start"]) * 512
            size = int(p["size"]) * 512
            name = p.get("name", f"part{idx}")

            part_tmp_file = os.path.join(tmpdir, "part.img")
            part_file = os.path.join(out, name + fmt.ext)

            if partition_is_safe_to_truncate(p):
                size = truncate_partition_size(image_file, start, size)
                if size == 0:
                    continue  # Skip empty partitions

            extract_part_of_file(
                image_file,
                part_tmp_file,
                start,
                size,
            )
            fmt.convert_image(runner, part_tmp_file, part_file)
    else:
        fmt.convert_image(runner, image_file, out)
