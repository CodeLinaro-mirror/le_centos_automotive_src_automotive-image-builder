import os
import glob

from .exceptions import UnsupportedExport

EXPORT_DATAS = {
    "qcow2": {"desc": "Disk image in qcow2 format", "filename": "disk.qcow2"},
    "image": {"desc": "Raw disk image", "filename": "disk.img"},
    "ostree-commit": {
        "desc": "OSTree repo containing a commit",
        "filename": "repo",
        "is_dir": True,
    },
    "container": {"desc": "Container image", "filename": "container.tar"},
    "ostree-oci-image": {
        "desc": "Container OCI image archive",
        "filename": "image.oci-archive",
    },
    "rootfs": {
        "desc": "Directory with image rootfs files",
        "filename": None,
        "is_dir": True,
        "no_chown": True,
    },
    "ext4": {
        "desc": "Ext4 filesystem image without partitions",
        "filename": "rootfs.ext4",
    },
    "tar": {
        "desc": "Tar archive with files from rootfs",
        "filename": "rootfs.tar",
    },
    "aboot": {
        "desc": "Aboot image",
        "filename": "images",
        "is_dir": True,
    },
    "rpmlist": {
        "desc": "List of rpms that are in the image",
        "filename": "rpmlist",
    },
    "ext4.simg": {
        "desc": "Ext4 filesystem partition in simg format",
        "export_arg": "ext4",
        "filename": "rootfs.ext4",
        "convert": "simg",
    },
    "simg": {
        "desc": "Partitioned image in simg format",
        "export_arg": "image",
        "filename": "disk.img",
        "convert": "simg",
    },
    "aboot.simg": {
        "desc": "Aboot image in simg format",
        "export_arg": "aboot",
        "filename": "images",
        "is_dir": True,
        "convert": "simg",
        "convert_filename": "images/*.ext4",
    },
}


def get_export_data(exp):
    if exp in EXPORT_DATAS:
        return EXPORT_DATAS[exp]
    raise UnsupportedExport(exp)


def export(outputdir, dest, dest_is_directory, export, runner):
    data = get_export_data(export)
    export = data.get("export_arg", export)
    exportdir = os.path.join(outputdir, export)
    export_is_dir = data.get("is_dir", False)

    filename = data["filename"]
    if filename:
        export_file = os.path.join(exportdir, filename)
    else:
        export_file = os.path.join(exportdir)

    convert = data.get("convert", "")
    if convert == "simg":
        if "convert_filename" in data:
            convert_files = glob.glob(os.path.join(exportdir, data["convert_filename"]))
        else:
            convert_files = [export_file]
        for convert_file in convert_files:
            converted_file = os.path.splitext(convert_file)[0] + ".simg"
            runner.run(
                ["img2simg", convert_file, converted_file],
                use_sudo=True,
                use_container=True,
            )
            runner.run(["rm", "-rf", convert_file], use_sudo=True)

        if not export_is_dir:
            export_file = converted_file

    if dest_is_directory:
        dest = os.path.join(dest, os.path.basename(export_file))

    if export_is_dir:
        # The mv won't replace existing destination, so first remove it
        if os.path.isdir(dest) or os.path.isfile(dest):
            runner.run(["rm", "-rf", dest], use_sudo=True)

    if not data.get("no_chown", False):
        runner.run(
            ["chown", f"{os.getuid()}:{os.getgid()}", export_file],
            use_sudo=True,
        )

    runner.run(["mv", export_file, dest], use_sudo=True)
