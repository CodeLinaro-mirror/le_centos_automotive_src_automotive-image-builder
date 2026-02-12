#!/usr/bin/env python3

"""Argument parsing structures and utilities for automotive-image-builder."""

import argparse
import collections
import os
import platform
import sys
from dataclasses import dataclass, field
from typing import Callable, List, Dict, Any
from enum import Enum

from .utils import DiskFormat
from .version import get_version
from . import log
from .globals import default_distro, default_container_image_name, default_bib_container


def aib_build_container_name(distro):
    """Generate the name for an AIB build container."""
    return f"localhost/aib-build:{distro}"


class CommandGroup(Enum):
    """Groups for CLI commands."""

    BASIC = "Basic image building"
    BOOTC = "Bootc operations"
    OTHER = "Other commands"
    HIDDEN = "Hidden"


@dataclass
class SubCommand:
    """
    Definition of a CLI subcommand.

    Attributes:
        name: The subcommand name (e.g., "build")
        help: Short help text shown in command list
        description: Long description shown in subcommand --help
        callback: Function to call when this subcommand is invoked
        shared_args: List of shared argument groups to include (e.g., ["container", "include"])
        args: Additional argument definitions specific to this subcommand (list of dicts)
    """

    name: str
    help: str
    description: str
    callback: Callable
    shared_args: List[str] = field(default_factory=list)
    args: List[Dict[str, Any]] = field(default_factory=list)


# Registry for full subcommand definitions (Group -> List[SubCommand])
command_registry = collections.defaultdict(list)


def command(
    name=None,
    help="",
    description="",
    group=CommandGroup.OTHER,
    shared_args=None,
    args=None,
):
    """
    Decorator to register a function as a command callback.

    Usage:
    @command(
        help="Build a bootc container image",
        group=CommandGroup.BOOTC,
        shared_args=["container", "include"],
        args=[BUILD_ARGS],
    )
    def build_bootc(args, tmpdir, runner):
        \"\"\"Build a bootc container image\"\"\"
        ...


    Args:
        name: Optional name to register this callback under.
              If None, uses the function's __name__ with underscores replaced by hyphens
              (e.g. 'build_builder' -> 'build-builder')
        help: Short help text shown in command list
        description: Long description shown in subcommand --help.
                     If not provided, uses the docstring of the function.
        group: The group this command belongs to (CommandGroup or str)
        shared_args: List of shared argument groups to include
        args: Additional argument definitions specific to this subcommand

    Returns:
        The decorator function
    """

    def decorator(func):
        callback_name = name
        if callback_name is None:
            callback_name = func.__name__.replace("_", "-")

        # Use docstring as description if not provided
        desc = description
        if not desc and func.__doc__:
            desc = func.__doc__

        cmd = SubCommand(
            name=callback_name,
            help=help,
            description=desc,
            callback=func,
            shared_args=shared_args or [],
            args=args or [],
        )

        command_registry[group].append(cmd)
        return func

    return decorator


class AIBHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Custom help formatter that groups subcommands."""

    def _format_action(self, action):
        # Intercept the subparsers block and add subcommand groups
        if isinstance(action, argparse._SubParsersAction):
            sub_actions = {}
            for sub_action in action._get_subactions():
                name = getattr(sub_action, "dest", None)
                sub_actions[name] = sub_action

            groups = collections.defaultdict(list)
            for name, subp in action.choices.items():
                group = getattr(subp, "_group", "Commands")
                subaction = sub_actions[name]
                groups[group].append((name, subaction.help))

            # Render like argparse, but in grouped sections
            parts = []
            for group_name, entries in groups.items():
                parts.append(f"\n{group_name}:")
                maxlen = max(len(n) for n, _ in entries) if entries else 0
                for n, h in entries:
                    parts.append(
                        f"  {n.ljust(maxlen)}  {h if h != '==SUPPRESS==' else ''}"
                    )
            parts.append("")
            return "\n".join(parts)
        return super()._format_action(action)


def add_arg(parser, groups, name, data, suppress_default=False, suppress_help=False):
    """Add a single argument to a parser."""
    if isinstance(data, str):
        data = {"help": data}

    groupname = data.get("exclusive-group", None)
    if groupname:
        if groupname not in groups:
            groups[groupname] = parser.add_mutually_exclusive_group()
        dst = groups[groupname]
    else:
        dst = parser

    t = data.get("type", "bool" if name.startswith("-") else "str")

    # Determine default value (normal or SUPPRESS for subparsers)
    # SUPPRESS prevents subparsers from setting a default value, which would otherwise
    # overwrite any value already captured by the main parser. This allows shareable
    # arguments to work both before and after subcommands (e.g., both
    # `aib --container build ...` and `aib build --container ...`)
    if suppress_default:
        default = argparse.SUPPRESS
    elif t == "bool":
        default = False
    elif t == "append":
        default = []
    else:
        default = None

    if t == "bool":
        a = dst.add_argument(name, default=default, action="store_true")
    elif t == "bool-optional":
        # bool-optional doesn't need suppress_default handling
        a = dst.add_argument(name, action=argparse.BooleanOptionalAction)
    elif t == "diskformat":
        a = dst.add_argument(
            name,
            action="store",
            type=str,
            choices=[f.value for f in DiskFormat],
            default=default,
        )
    elif t == "version":
        # version doesn't need suppress_default handling
        a = dst.add_argument(
            name, action="version", version=f"%(prog)s {get_version()}"
        )
    elif t == "str" or t == "path":
        a = dst.add_argument(
            name,
            action="store",
            type=str,
            default=default,
        )
    elif t == "append":
        a = dst.add_argument(
            name,
            action="append",
            type=str,
            default=default,
        )
    else:
        log.error("Unknown arg type %s", t)

    if suppress_help:
        a.help = argparse.SUPPRESS
    elif "help" in data:
        a.help = data["help"]
    if "required" in data:
        a.required = data["required"]
    if "default" in data and not suppress_default:
        a.default = data["default"]
    if "metavar" in data:
        a.metavar = data["metavar"]
    elif t == "path":
        a.metavar = "PATH"


def add_args(parser, groups, args, suppress_default=False, suppress_help=False):
    """Add multiple arguments to a parser."""
    for name, data in args.items():
        add_arg(
            parser,
            groups,
            name,
            data,
            suppress_default=suppress_default,
            suppress_help=suppress_help,
        )


# Arguments for no subcommand
GLOBAL_ARGS = {
    "--version": {"type": "version"},
}

# Arguments for all subcommands
COMMON_ARGS = {
    "--verbose": {"help": "Print verbose output"},
}

# Shareable argument groups that can be used before or after subcommands (for historical reasons)
SHAREABLE_ARGS = {
    "container": {
        "--container": "Run build commands in a container (see --container-image-name)",
        "--user-container": "Use rootless containerized build",
        "--user-storage": {
            "help": (
                "Avoid sudo for storage operations (podman/skopeo). "
                "Use when CONTAINERS_STORAGE_CONF points to user-owned storage."
            ),
        },
        "--container-image-name": {
            "type": "str",
            "metavar": "IMAGE",
            "default": default_container_image_name,
            "help": f"Container image user for --container (default: {default_container_image_name})",
        },
        "--container-autoupdate": "Automatically pull new container image if available",
    },
    "include": {
        "--include": {
            "type": "append",
            "help": "Add include directory to extend available distros and targets",
        },
    },
}

LIST_ARGS = {"--quiet": {"help": "Only print the names, no descriptive text"}}

POLICY_ARGS = {
    "--policy": {
        "type": "str",
        "help": "Specify a policy file that restricts what build options are used",
    },
}
TARGET_ARGS = {
    "--target": {
        "type": "str",
        "help": "Build for this target hardware board (see list-targets for options)",
    },
}
BUILD_ARGS = {
    "--distro": {
        "type": "str",
        "default": default_distro,
        "help": "Build for this distro specification and version (see list-distro for options)",
    },
    "--arch": {
        "default": platform.machine(),
        "type": "str",
        "help": f"Architecture to build for (default {platform.machine()})",
    },
    "--build-dir": {
        "type": "path",
        "default": os.getenv("OSBUILD_BUILDDIR"),
        "help": "Directory where intermediary files are stored",
    },
    "--cache-max-size": {
        "type": "str",
        "metavar": "SIZE",
        "help": "Max cache size inside build-dir, e.g. '8GB', or 'unlimited'",
    },
    "--cache": {
        "type": "str",
        "help": "Set dnf cache directory to use (default: none)",
    },
    "--logfile": {
        "type": "path",
        "default": None,
        "help": (
            "Path to file to write logs to. "
            "Default is <build-dir>/automotive-image-builder-[timestamp].log"
        ),
    },
    "--progress": {
        "type": "bool-optional",
        "help": "Enable or disable progress bar (default: enabled in terminal)",
        "default": sys.stdout.isatty(),
    },
    "--osbuild-manifest": {
        "type": "path",
        "help": "Path to export the generated osbuild manifest that was used when building the image",
    },
    "--local-repo": {
        "type": "path",
        "default": None,
        "help": "Install rpms from a local repository at the given path",
    },
    "--define": {
        "type": "append",
        "metavar": "KEY=VALUE",
        "help": "Define internal variable key to a specified value",
    },
    "--extend-define": {
        "type": "append",
        "metavar": "KEY=VALUE",
        "help": "Extend internal variable array by item or list",
    },
    "--define-file": {
        "type": "append",
        "metavar": "PATH",
        "help": "Add internal defines from a yaml dictionary in a file",
    },
    "--dump-variables": "Dump internal variables that would be used when building and exit.",
}
DISK_FORMAT_ARGS = {
    "--format": {
        "type": "diskformat",
        "help": "Disk image format (default: from extension)",
    },
    "--separate-partitions": {
        "help": "Split disk images into per-partition files",
    },
    "--vm": {
        "type": "bool-optional",
        "help": "Use VM to build disk image (default off)",
        "default": False,
    },
}
BIB_ARGS = {
    "--bib-container": {
        "type": "str",
        "metavar": "IMAGE",
        "default": default_bib_container,
        "help": f"bootc-image-builder image to use (default: {default_bib_container})",
    },
    "--build-container": {
        "type": "str",
        "metavar": "IMAGE",
        "help": f"bootc build container image to use (default: {aib_build_container_name('$DISTRO')})",
    },
}
SHARED_RESEAL_ARGS = {
    "--build-container": {
        "type": "str",
        "help": "bootc build container image to use",
    },
    "--passwd": {
        "type": "str",
        "help": "openssl password source for --key, see openssl-passphrase-options manpage for format",
    },
}


def no_subcommand(_args, _tmpdir, _runner):
    """Print a message when no subcommand is specified."""
    log.info("No subcommand specified, see --help for usage")


def parse_args(args, prog="aib"):
    """
    Parse command-line arguments.

    Args:
        args: List of command-line arguments to parse

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Select subcommand to run.\n"
        "For more details, use --help for the individual commands.",
        formatter_class=AIBHelpFormatter,
    )
    parser._positionals.title = None
    parser._optionals.title = "Global options"
    add_args(parser, {}, GLOBAL_ARGS)
    add_args(parser, {}, COMMON_ARGS)
    # Add shareable args to main parser with normal defaults, but no help
    for arg_dict in SHAREABLE_ARGS.values():
        add_args(parser, {}, arg_dict, suppress_default=False, suppress_help=True)
    parser.set_defaults(func=no_subcommand)

    subparsers = parser.add_subparsers()

    groups_to_process = [
        (group_enum.value, command_registry.get(group_enum, []))
        for group_enum in CommandGroup
        if group_enum != CommandGroup.HIDDEN
    ]

    # 2. Any other custom groups
    for group_key, subcmds in command_registry.items():
        if not isinstance(group_key, CommandGroup):
            groups_to_process.append((str(group_key), subcmds))

    for group_name, subcmds in groups_to_process:
        if not subcmds:
            continue

        for subcmd in subcmds:
            arg_groups = {}

            subparser = subparsers.add_parser(
                subcmd.name,
                help=subcmd.help,
                description=subcmd.description,
                formatter_class=argparse.RawDescriptionHelpFormatter,
            )
            subparser.set_defaults(func=subcmd.callback)
            subparser._group = group_name

            # Add remaining args
            for _args in subcmd.args:
                add_args(subparser, arg_groups, _args)

            # Add shareable args to subparser with SUPPRESS default to preserve main parser values
            # This allows arguments to work in both positions without overwriting each other
            add_args(subparser, {}, COMMON_ARGS, suppress_default=True)
            for key in subcmd.shared_args:
                add_args(
                    subparser, arg_groups, SHAREABLE_ARGS[key], suppress_default=True
                )

    return parser.parse_args(args)
