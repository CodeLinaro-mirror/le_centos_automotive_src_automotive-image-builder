import os
from enum import Enum
from pathlib import Path

# Detection of the execution environment (privilege level and container state)
# and the resulting policy for how we run privileged tools and clean up after
# them.

# Env vars that survive into a sudo-invoked command.
PRESERVED_ENV = [
    "REGISTRY_AUTH_FILE",
    "CONTAINERS_CONF",
    "CONTAINERS_REGISTRIES_CONF",
    "CONTAINERS_STORAGE_CONF",
]


class ContainerState:
    _cache = None

    def __init__(self):
        self.in_container = False
        self.in_rootless_container = False

        p = Path("/run/.containerenv")
        if p.exists():
            self.in_container = True
            with p.open("r") as f:
                for line in f.read().splitlines():
                    if line == "rootless=1":
                        self.in_rootless_container = True
                        break

    def __str__(self):
        state_parts = [
            f"in_container={self.in_container}",
            f"in_rootless_container={self.in_rootless_container}",
        ]
        return f"ContainerState({', '.join(state_parts)})"

    @classmethod
    def query(cls):
        if not cls._cache:
            cls._cache = cls()
        return cls._cache


class Privilege(Enum):
    ROOT = "root"  # real uid 0: bare metal or rootful container
    ROOTLESS_CONTAINER = "rootless-container"  # fake-root inside rootless container
    SUDO = "sudo"  # unprivileged user, escalate via sudo1
    ROOTLESS = "rootless"  # unprivileged user, run tools rootless


class ExecMode:
    _current = None

    def __init__(self, privilege):
        self.privilege = privilege

    @classmethod
    def resolve(cls, use_sudo):
        state = ContainerState.query()
        if state.in_rootless_container:
            priv = Privilege.ROOTLESS_CONTAINER
        elif os.getuid() == 0:
            priv = Privilege.ROOT
        elif use_sudo:
            priv = Privilege.SUDO
        else:
            priv = Privilege.ROOTLESS
        cls._current = cls(priv)
        return cls._current

    @classmethod
    def current(cls):
        # Fall back to the default (sudo when unprivileged) if resolve() was
        # never called, e.g. in unit tests that don't parse arguments.
        if cls._current is None:
            cls.resolve(use_sudo=True)
        return cls._current

    @property
    def uses_sudo(self):
        return self.privilege == Privilege.SUDO

    @property
    def run_prefix(self):
        """Prefix to launch a privilege-requiring build tool."""
        if self.privilege == Privilege.SUDO:
            return ["sudo", "--preserve-env={}".format(",".join(PRESERVED_ENV))]
        # ROOTLESS: The those tools handle permissions internally as needed
        # ROOT: No need, we're already root
        # ROOTLESS_CONTAINER: No need, we're already "fake" root
        return []

    @property
    def reap_prefix(self):
        """Prefix to remove/unmount trees a tool left behind, which
        may contain files with weird ownership."""
        if self.privilege == Privilege.SUDO:
            return ["sudo"]
        if self.privilege == Privilege.ROOTLESS:
            # This gives us access to all the uid/gids that the user
            # has access to in /etc/subuids
            return ["podman", "unshare"]
        return []

    @property
    def force_in_vm(self):
        # No real root for the privileged osbuild pipelines, run them in a VM.
        return self.privilege in (Privilege.ROOTLESS_CONTAINER, Privilege.ROOTLESS)

    @property
    def osbuild_store_subdir(self):
        # In rootless mode, the on-disk uid/gids are stored as per the users
        # subuids, so it is not compatible with rootfull tool output.
        if self.privilege in (Privilege.ROOTLESS_CONTAINER, Privilege.ROOTLESS):
            return "osbuild_store_rootless"
        return "osbuild_store"

    @property
    def podman_needs_unshare(self):
        # A plain unprivileged user needs "podman unshare" prefix to access podman mounts
        return self.privilege == Privilege.ROOTLESS

    def __str__(self):
        return f"ExecMode({self.privilege.value})"
