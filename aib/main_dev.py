#!/usr/bin/env python3

import sys
import os

from .utils import (
    DiskFormat,
)
from .exports import export, get_export_data
from .runner import Runner
from .utils import (
    SudoTemporaryDirectory,
)
from . import exceptions
from . import AIBParameters
from . import log
from .arguments import (
    parse_args,
    command,
    POLICY_ARGS,
    TARGET_ARGS,
    BUILD_ARGS,
    DISK_FORMAT_ARGS,
    CommandGroup,
)
from .podman import (
    ContainerStorage,
)
from .osbuild import (
    create_osbuild_manifest,
    extract_rpmlist_json,
    run_osbuild,
    export_disk_image_file,
)

from . import list_ops  # noqa: F401

base_dir = os.path.realpath(sys.argv[1])


@command(
    name="list-rpms",
    help="List the rpms that a manifest would use when built",
    shared_args=["container", "include"],
    args=[
        TARGET_ARGS,
        BUILD_ARGS,
        {
            # TODO: We should drop --mode when build command is dropped
            "--mode": {
                "type": "str",
                "default": "image",
                "help": "Build this image mode (package, image)",
            },
            "manifest": "Source manifest file",
        },
    ],
)
def listrpms(args, tmpdir, runner):
    """List the rpms that a manifest would use when build"""
    osbuild_manifest = os.path.join(tmpdir, "osbuild.json")

    create_osbuild_manifest(args, tmpdir, osbuild_manifest, runner)

    data = extract_rpmlist_json(osbuild_manifest)

    print(data)


@command(
    group=CommandGroup.BASIC,
    help="Backwards compatible a-i-b 1.0 build command (deprecated)",
    shared_args=["container", "include"],
    args=[
        {
            "--mode": {
                "type": "str",
                "default": "image",
                "help": "Build this image mode (package, image)",
            },
            "--ostree-repo": {
                "type": "path",
                "help": "Export ostree commit to ostree repo at this path",
            },
            "--export": {
                "type": "append",
                "help": "Export this image type",
            },
            "manifest": "Source manifest file",
            "out": "Output path",
        },
        POLICY_ARGS,
        TARGET_ARGS,
        BUILD_ARGS,
    ],
)
def build_deprecated(args, tmpdir, runner):
    """
    Backwards compatibility command to build various types of images.
    This takes '--mode' and '--export' options that together define
    what to build and how.

    This command is deprecated, and we now recommend using 'build'
    instead, as this are easier to use, and  avoid accidentally using
    problematic combination of image options
    """
    has_repo = False
    exports = []

    is_bootc = False
    # Rewrite exports according to export_data
    for exp in args.export:
        if "bootc" in exp:
            is_bootc = True
        data = get_export_data(exp)
        exp = data.get("export_arg", exp)
        exports.append(exp)
        if exp == "ostree-commit":
            has_repo = True

    # Rewrite --mode image and --export bootc... to mode=bootc
    if is_bootc:
        if args.mode != "image":
            raise exceptions.AIBException(f"mode {args.mode} not compabible with bootc")
        args.mode = "bootc"

    # If ostree repo was specified, also export it if needed
    if not has_repo and args.ostree_repo:
        exports += ["ostree-commit"]

    with run_osbuild(args, tmpdir, runner, exports) as outputdir:
        if args.ostree_repo:
            repodir = os.path.join(outputdir.name, "ostree-commit/repo")
            runner.run_as_user(
                ["ostree", "pull-local", "--repo=" + args.ostree_repo, repodir]
            )

        if len(args.export) == 0:
            pass
        elif len(args.export) == 1:
            # Export directly to args.out
            export(outputdir.name, args.out, False, args.export[0], runner)
        else:
            if os.path.isdir(args.out) or os.path.isfile(args.out):
                runner.run_as_root(["rm", "-rf", args.out])
            os.mkdir(args.out)
            for exp in args.export:
                export(outputdir.name, args.out, True, exp, runner)


@command(
    group=CommandGroup.BASIC,
    help="Build a traditional, package based, disk image file",
    shared_args=["container", "include"],
    args=[
        DISK_FORMAT_ARGS,
        {
            "--dry-run": {
                "help": "Just compose the osbuild manifest, don't build it.",
            },
            "manifest": "Source manifest file",
            "out": "Output path",
        },
        POLICY_ARGS,
        TARGET_ARGS,
        BUILD_ARGS,
    ],
)
def build(args, tmpdir, runner):
    """
    Builds a disk image from a manifest describing its content, and options like what
    board to target and what distribution version to use.

    The creates disk image has a mutable, package-base regular rootfs (i.e. it is not
    using image mode).
    """
    args.mode = "package"

    fmt = DiskFormat.from_string(args.format) or DiskFormat.from_filename(args.out)

    exports = []
    if not args.dry_run:
        exports.append("image")

    in_vm = []
    if args.vm:
        in_vm.append("image")

    storage = ContainerStorage(args.container_storage, tmpdir, args.user_container)

    with run_osbuild(
        args, tmpdir, runner, exports, in_vm=in_vm, storage=storage
    ) as outputdir:
        output_file = os.path.join(outputdir.name, "image/disk.img")

        if not args.dry_run:
            export_disk_image_file(runner, args, tmpdir, output_file, args.out, fmt)


@command(
    help="Download all sources that are needed to build an image",
    shared_args=[],
    args=[
        TARGET_ARGS,
        BUILD_ARGS,
        {
            "manifest": "Source manifest file",
        },
    ],
)
def download(args, tmpdir, runner):
    """
    This downloads all the source files that would be downloaded when an image is built
    It is a good way to pre-seed a --build-dir that is later used with multiple image
    builds.
    """
    if not args.build_dir:
        log.error("No build dir specified, refusing to download to temporary directory")
        sys.exit(1)
    args.out = None
    args.mode = "image"
    exports = []

    outputdir = run_osbuild(args, tmpdir, runner, exports)
    outputdir.cleanup()


def main():
    parsed_args = parse_args(sys.argv[2:], prog="aib-dev")
    args = AIBParameters(parsed_args, base_dir)

    runner = Runner(args)
    runner.add_volume(os.getcwd())

    with SudoTemporaryDirectory(
        prefix="automotive-image-builder-", dir="/var/tmp"
    ) as tmpdir:
        runner.add_volume(tmpdir)
        try:
            return args.func(tmpdir, runner)
        except KeyboardInterrupt:
            log.info("Build interrupted by user")
            sys.exit(130)
        except (exceptions.AIBException, FileNotFoundError) as e:
            log.error("%s", e)
            sys.exit(1)
        except Exception:
            log.error("Unexpected exception occurred!")
            raise


if __name__ == "__main__":
    sys.exit(main())
