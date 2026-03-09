#!/usr/bin/env python3

import binascii
import shutil
import sys
import os
import json
import subprocess

from .utils import (
    read_public_key,
    read_keys,
    generate_keys,
    DiskFormat,
)
from .runner import Runner
from .utils import (
    SudoTemporaryDirectory,
    rm_rf,
)
from . import exceptions
from .exceptions import (
    ContainerNotFound,
    BuildContainerNotFound,
    BootcImageBuilderFailed,
    IncompatibleOptions,
    InvalidBuildDir,
    UnknownSignatureType,
)
from . import AIBParameters
from . import log
from .podman import (
    ContainerState,
    ContainerStorage,
    podman_image_exists,
    podman_image_info,
    podman_run_bootc_image_builder,
    podman_bootc_inject_pubkey,
    PodmanImageMount,
    TemporaryContainer,
)
from .arguments import (
    parse_args,
    aib_build_container_name,
    command,
    BIB_ARGS,
    POLICY_ARGS,
    TARGET_ARGS,
    BUILD_ARGS,
    DISK_FORMAT_ARGS,
    SHARED_RESEAL_ARGS,
    CommandGroup,
)
from .osbuild import (
    create_osbuild_manifest,
    extract_rpmlist_json,
    run_osbuild,
    export_disk_image_file,
)
from .globals import default_distro, default_bib_container

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

    storage = ContainerStorage.from_args(args, tmpdir)

    create_osbuild_manifest(args, tmpdir, osbuild_manifest, runner, storage)

    data = extract_rpmlist_json(osbuild_manifest)

    print(data)


def bootc_archive_to_store(runner, archive_file, storage, container_name):
    """
    Copy a bootc OCI archive to container storage.
    """
    cmdline = [
        "skopeo",
        "copy",
        "--quiet",
        "oci-archive:" + archive_file,
        storage.skopeo(container_name),
    ]

    if storage.with_sudo:
        runner.run_as_root(cmdline)
    else:
        subprocess.run(cmdline, check=True)


def container_to_disk_image(args, tmpdir, runner, storage, src_container, fmt, out):
    with SudoTemporaryDirectory(
        prefix="bib-out--", dir=os.path.dirname(out)
    ) as outputdir:
        output_file = os.path.join(outputdir.name, "image.raw")
        build_container = args.build_container or get_build_container_for(
            storage, src_container
        )

        bib_container = args.bib_container_image

        # WIP: image-builder doesn't yet support --in-vm, so in some
        # cases we have fall back to bootc-image-builder by default:
        if args.vm and not bib_container:
            state = ContainerState.query()

            local_bcib_path = shutil.which("bootc-image-builder-local")
            if state.in_rootless_container and local_bcib_path:
                # We're in a rootless a-i-b container and can't use a recursive container for a-i-b
                # so instead run bc-i-b directly in the same container
                bib_container = local_bcib_path
            else:
                bib_container = default_bib_container

        if bib_container:
            res = podman_run_bootc_image_builder(
                bib_container,
                storage,
                build_container,
                src_container,
                "raw",
                output_file,
                args.vm,
                args.user_container,
                args.verbose,
            )
            if res != 0:
                raise BootcImageBuilderFailed()
        else:
            # Fall back to the use of image-builder instead of bc-i-b container
            runner.add_volume("/dev")
            runner.add_volume(tmpdir)
            cachedir = os.path.join(tmpdir, "cache")
            os.mkdir(cachedir)
            rpmmddir = os.path.join(tmpdir, "rpmmd")
            os.mkdir(rpmmddir)
            cmdline = [
                "image-builder",
                "--cache",
                cachedir,
                "--rpmmd-cache",
                rpmmddir,
                "--output-dir",
                outputdir.name,
                "--output-name",
                "image",
                "--bootc-build-ref",
                build_container,
                "--bootc-ref",
                src_container,
            ]

            if args.verbose:
                cmdline += ["--progress", "verbose"]

            if args.vm:
                cmdline += ["--in-vm"]

            cmdline += ["build", "raw"]

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
                verbose=args.verbose,
                extra_volumes=volumes,
            )

        export_disk_image_file(runner, args, tmpdir, output_file, out, fmt)


def random_container_name():
    return "localhost/aib-" + binascii.b2a_hex(os.urandom(12)).decode("utf8")


@command(
    group=CommandGroup.BASIC,
    help="Build a bootc container image (to container store or archive file) and optionally disk image",
    shared_args=["container", "include"],
    args=[
        {
            "--oci-archive": {
                "help": "Build an oci container archive file instead of a container image",
            },
            "--tar": {
                "help": "Build a tar file with the container content instead of a container image",
            },
            "--dry-run": {
                "help": "Just compose the osbuild manifest, don't build it.",
            },
            "manifest": "Source manifest file",
            "out": "Output container image name (or pathname), or '-' to not store container",
            "disk": {
                "help": "Optional output disk image pathname",
                "required": False,
            },
        },
        POLICY_ARGS,
        TARGET_ARGS,
        BUILD_ARGS,
        DISK_FORMAT_ARGS,
        BIB_ARGS,
    ],
)
def build(args, tmpdir, runner):
    """
    This builds a bootc-style container image from a manifest describing its
    content, and options like what board to target and what distribution version
    to use. Optionally it can also build a disk image, but this can also be done
    later with the `to-disk-image` command.

    The resulting container image can used to update a running bootc system, using
    `bootc update` or `bootc switch`.
    """
    args.mode = "bootc"

    exports = []
    if not args.dry_run:
        exports.append("bootc-tar" if args.tar else "bootc-archive")

    in_vm = []
    if args.vm:
        in_vm.append("image")

    if args.disk and args.tar:
        raise IncompatibleOptions(
            option1="--tar",
            option2="generating disk image",
            reason="tar format is only for container archives",
        )

    # This is the container name we use in the root container store.
    # It may be a random temporary name if the user didn't want the result in the
    # root container store (i.e. user store or oci archive file)
    containername = None
    remove_container = False

    storage = ContainerStorage.from_args(args, tmpdir)

    with run_osbuild(
        args, tmpdir, runner, exports, in_vm=in_vm, storage=storage
    ) as outputdir:
        if args.tar:
            output_file = os.path.join(outputdir.name, "bootc-tar/rootfs.tar")
        else:
            output_file = os.path.join(
                outputdir.name, "bootc-archive/image.oci-archive"
            )

        # Export to file and/or container store as needed
        if args.dry_run:
            pass
        elif args.tar or args.oci_archive:
            if args.disk and args.oci_archive:
                # We need it in the store, to convert it
                remove_container = True
                containername = random_container_name()
                bootc_archive_to_store(runner, output_file, storage, containername)

            runner.add_volume_for(args.out)
            runner.move_chown(output_file, args.out)
        else:
            # "-" to not store result in store
            if args.out != "-":
                containername = args.out
            elif args.disk:
                # We need it in the store anyway to convert it, but use a random name
                remove_container = True
                containername = random_container_name()

            if containername:
                bootc_archive_to_store(
                    runner,
                    output_file,
                    storage,
                    containername,
                )

    if args.disk and not args.dry_run:
        assert containername is not None
        fmt = DiskFormat.from_string(args.format) or DiskFormat.from_filename(args.disk)
        with TemporaryContainer(storage, containername, cleanup=remove_container):
            container_to_disk_image(
                args, tmpdir, runner, storage, containername, fmt, args.disk
            )


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
        raise InvalidBuildDir()
    args.out = None
    args.mode = "image"
    exports = []

    outputdir = run_osbuild(args, tmpdir, runner, exports)
    outputdir.cleanup()


@command(
    group=CommandGroup.BASIC,
    help="Build helper bootc image used by to-disk-image",
    shared_args=["container", "include"],
    args=[
        BUILD_ARGS,
        {
            "--if-needed": {
                "help": "Only build the image if its not already built.",
            },
            "--oci-archive": {
                "help": "Build an oci container archive file instead of a container image",
            },
            "out": {
                "help": "Name of container image to build",
                "required": False,
            },
        },
    ],
)
def build_builder(args, tmpdir, runner):
    """
    This command produces a bootc image containing required tools that is used
    in the to-disk-image (and reseal) command. This will contain tools
    like mkfs.ext4 that are needed to build a disk image.

    In non-automotive use of bootc, these tools are in the bootc image itself,
    but since automotive images are very minimal these need to come from another
    source. The tools need to match the version of the image, so these
    containers are built for specific distro versions.

    The container to use in to-disk-image can be specified with --build-container,
    but normally the default name of 'localhost/aib-build:$DISTRO' is used, and if
    the out argument is not specified this will be used.
    """
    # build-builder is a special form of the "build" command with fixed values for
    # manifest/export/target/mode arguments.
    args.simple_manifest = os.path.join(args.base_dir, "files/bootc-builder.aib.yml")
    args.manifest = os.path.join(args.base_dir, "files/simple.mpp.yml")
    args.target = "qemu"
    args.mode = "bootc"

    dest_image = args.out or aib_build_container_name(args.distro)

    storage = ContainerStorage.from_args(args, tmpdir)

    if args.if_needed:
        info = podman_image_info(storage, dest_image)
        if info:
            print(f"Image {dest_image} already exists, doing nothing.")
            return

    with run_osbuild(args, tmpdir, runner, ["bootc-archive"]) as outputdir:
        output_file = os.path.join(outputdir.name, "bootc-archive/image.oci-archive")

        if args.oci_archive:
            runner.add_volume_for(args.out)
            runner.move_chown(output_file, args.out)
        else:
            bootc_archive_to_store(runner, output_file, storage, dest_image)

        print(f"Built image {dest_image}")


def get_build_container_for(storage, container):
    info = podman_image_info(storage, container)
    if not info:
        raise ContainerNotFound(container)

    # Use same distro for build image as the source container image
    distro = default_distro
    if info.build_info:
        distro = info.build_info.get("DISTRO", distro)

    build_container = aib_build_container_name(distro)
    if not podman_image_exists(storage, build_container):
        raise BuildContainerNotFound(build_container, distro)
    return build_container


@command(
    group=CommandGroup.BOOTC,
    help="Build a physical disk image based on a bootc container",
    shared_args=["container"],
    args=[
        DISK_FORMAT_ARGS,
        BIB_ARGS,
        {
            "src_container": "Bootc container name",
            "out": "Output image name",
        },
    ],
)
def to_disk_image(args, tmpdir, runner):
    """
    Converts a bootc container image to a disk image that can be flashed on a board

    Internally this uses the bootc-image-builder tool from a container image.
    The --bib-container-image option can be used to specify a different version of this tool

    Also, to build the image we need a container with tools. See the build-builder
    command for how to build one.
    """

    storage = ContainerStorage.from_args(args, tmpdir)

    if not podman_image_exists(storage, args.src_container):
        raise ContainerNotFound(args.src_container)

    fmt = DiskFormat.from_string(args.format) or DiskFormat.from_filename(args.out)

    container_to_disk_image(
        args, tmpdir, runner, storage, args.src_container, fmt, args.out
    )


@command(
    group=CommandGroup.BOOTC,
    help="Extract files for secure-boot signing",
    shared_args=["container"],
    args=[
        {
            "src_container": "Bootc container name",
            "out": "Output directory",
        },
    ],
)
def extract_for_signing(args, tmpdir, runner):
    """
    Extract all the files related to secure boot that need signing in the image. This can
    be for example EFI executables, or aboot partition data.

    These files can then be signed, using whatever process available to the user, which
    often involves sending them to a 3rd party. Once these files are signed, the modified
    file can then be injected using inject-signed.
    """
    storage = ContainerStorage(args.container_storage, tmpdir, args.user_container)

    if not podman_image_exists(storage, args.src_container):
        raise ContainerNotFound(args.src_container)
    rm_rf(args.out)
    os.makedirs(args.out)
    with PodmanImageMount(storage, args.src_container) as mount:
        if mount.has_file("/etc/signing_info.json"):
            content = mount.read_file("/etc/signing_info.json")
            info = json.loads(content)

            with open(os.path.join(args.out, "signing_info.json"), "w") as f:
                f.write(content)
            for f in info.get("signed_files", []):
                _type = f["type"]
                filename = f["filename"]
                src = f["paths"][0]  # All files should be the same, copy out first

                if _type == "efi":
                    destdir = os.path.join(args.out, "efi")
                elif _type in ["aboot", "vbmeta"]:
                    destdir = os.path.join(args.out, "aboot")
                else:
                    raise UnknownSignatureType(_type)

                os.makedirs(destdir, exist_ok=True)

                log.info("Extracting %s from %s", filename, src)
                dest = os.path.join(destdir, filename)
                mount.copy_out_file(src, dest)
        else:
            log.info("No /etc/signing_info.json, nothing to sign")
            sys.exit(0)


def do_reseal_image(
    args, runner, tmpdir, privkey, storage, src_container, dst_container
):
    privkey_file = os.path.join(tmpdir, "pkey")
    with os.fdopen(
        os.open(privkey_file, os.O_CREAT | os.O_WRONLY, mode=0o600), "w"
    ) as f:
        f.write(privkey)

    # rpm-ostree only looks in the default (host or user depending on uid) container store
    # so we need to use env-vars to override it.
    volumes = {storage.storage: storage.storage}

    runner.run_in_container(
        [
            "env",
            f"CONTAINERS_STORAGE_CONF={storage.get_config_path()}",
            "rpm-ostree",
            "experimental",
            "compose",
            "build-chunked-oci",
            "--sign-commit",
            f"ed25519={privkey_file}",
            "--bootc",
            "--format-version=1",
            f"--from={src_container}",
            f"--output={storage.skopeo(dst_container)}",
        ],
        extra_volumes=volumes,
        stdout_to_devnull=not args.verbose,
        need_osbuild_privs=True,
    )


@command(
    group=CommandGroup.BOOTC,
    help="Inject files that were signed for secure-boot",
    shared_args=["container"],
    args=[
        SHARED_RESEAL_ARGS,
        {
            "--reseal-with-key": {
                "type": "path",
                "help": "re-seal image with given key",
            },
            "src_container": "Bootc container name",
            "srcdir": "Directory with signed files",
            "new_container": "Destination container name",
        },
    ],
)
def inject_signed(args, tmpdir, runner):
    """
    Once the files produced by extract-for-signing have been signed, this command
    can be used to inject them into the bootc image again.

    Note that this modified the bootc image which makes it not possible to boot if
    sealed images are being used (which is the default). Also, signatures interact
    in a complex way with sealing. See the help for reseal for how to re-seal
    the modified image so that it boots again.
    """
    storage = ContainerStorage.from_args(args, tmpdir)

    if not podman_image_exists(storage, args.src_container):
        raise ContainerNotFound(args.src_container)

    with PodmanImageMount(
        storage,
        args.src_container,
        writable=True,
        commit_image=None if args.reseal_with_key else args.new_container,
    ) as mount:
        if mount.has_file("/etc/signing_info.json"):
            content = mount.read_file("/etc/signing_info.json")
            info = json.loads(content)

            for f in info.get("signed_files", []):
                _type = f["type"]
                filename = f["filename"]

                if _type == "efi":
                    srcdir = os.path.join(args.srcdir, "efi")
                elif _type in ["aboot", "vbmeta"]:
                    srcdir = os.path.join(args.srcdir, "aboot")
                else:
                    raise UnknownSignatureType(_type)

                src = os.path.join(srcdir, filename)
                log.info("Injecting %s from %s", filename, src)

                for dest_path in f["paths"]:
                    mount.copy_in_file(src, dest_path)
        else:
            log.info("No /etc/signing_info.json, nothing needed signing")
            sys.exit(0)

    if args.reseal_with_key:
        _pubkey, privkey = read_keys(args.reseal_with_key, args.passwd)
        with TemporaryContainer(storage, mount.image_id) as temp_container:
            do_reseal_image(
                args,
                runner,
                tmpdir,
                privkey,
                storage,
                temp_container,
                args.new_container,
            )


@command(
    group=CommandGroup.BOOTC,
    help="Seal bootc image after it has been modified",
    shared_args=["container"],
    args=[
        SHARED_RESEAL_ARGS,
        {
            "--key": {
                "type": "path",
                "help": "path to private key, as previously used in prepare-reseal",
            },
            "src_container": "Bootc container name",
            "new_container": "Destination container name",
        },
    ],
)
def reseal(args, tmpdir, runner):
    """
    By default, bootc images are 'sealed', which means that the root filesystem
    is signed by a secret key. The (signed by secureboot) initramfs will contain
    the corresponding public key used to validate the root filesystem. If a
    bootc image is built to be sealed and it is later modified then this check
    will fail and the image will not boot. The reseal operation fixes this
    by updating the initramfs with a new public key and signing the rootfs with
    the (temporary) private key.

    Note: Re-sealing modifies the initramfs, which interacts badly with secureboot,
    where the initramfs is signed by a trusted key. To fix this issue there is a
    separate command 'prepare-reseal' that does the initial step of reseal
    i.e., it adds a new public key to the initrd. Once that is done, you can sign the
    new initramfs and then finish with prepare-reseal, passing in the key used
    in prepare-reseal to reseal with the --key option. See the help for
    prepare-reseal for more details
    """
    storage = ContainerStorage.from_args(args, tmpdir)
    if not podman_image_exists(storage, args.src_container):
        raise ContainerNotFound(args.src_container)

    if args.key:
        pubkey, privkey = read_keys(args.key, args.passwd)
        src_container = args.src_container
    else:
        pubkey, privkey = generate_keys()

        pubkey_file = os.path.join(tmpdir, "pubkey")
        with open(pubkey_file, "w", encoding="utf8") as f:
            f.write(pubkey)

        build_container = args.build_container
        if not build_container:
            build_container = get_build_container_for(storage, args.src_container)

        src_container = podman_bootc_inject_pubkey(
            storage,
            args.src_container,
            None,
            pubkey_file,
            build_container,
            args.user_container,
            args.verbose,
        )

    do_reseal_image(
        args, runner, tmpdir, privkey, storage, src_container, args.new_container
    )


@command(
    group=CommandGroup.BOOTC,
    help="Do the initial step of sealing and image, allowing further changes before actually sealing",
    shared_args=["container"],
    args=[
        SHARED_RESEAL_ARGS,
        {
            "--key": {
                "type": "path",
                "help": "path to private key file.",
                "required": True,
            },
            "src_container": "Bootc container name",
            "new_container": "Destination container name",
        },
    ],
)
def prepare_reseal(args, tmpdir, runner):
    """
    Injects the public part of a key pair into the initramfs of the bootc image, to
    prepare for signinging the initrd, and later calling reseal.

    The private key supplied should be single-use, used only for one image and discarded after
    it has been used in the matching reseal operation.

    A private key can be generated with openssl like this:
       openssl genpkey -algorithm ed25519 -outform PEM -out private.pem
    Optionally, `-aes-256-cbc` can be added to encrypt the private key with a password (which
    then has to be supplied when using it).
    """
    storage = ContainerStorage.from_args(args, tmpdir)
    if not podman_image_exists(storage, args.src_container):
        raise ContainerNotFound(args.src_container)

    build_container = args.build_container
    if not build_container:
        build_container = get_build_container_for(storage, args.src_container)

    pubkey = read_public_key(args.key, args.passwd)
    pubkey_file = os.path.join(tmpdir, "pubkey")

    with open(pubkey_file, "w", encoding="utf8") as f:
        f.write(pubkey)

    podman_bootc_inject_pubkey(
        storage,
        args.src_container,
        args.new_container,
        pubkey_file,
        build_container,
        args.user_container,
        args.verbose,
    )


def main():
    parsed_args = parse_args(sys.argv[2:])
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
