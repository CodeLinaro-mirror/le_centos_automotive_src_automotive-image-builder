import logging
import os
import sys
import time

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from .policy import PolicyLoader, PolicyError


@dataclass
class AIBParameters:
    args: Any
    base_dir: str

    def __init__(self, args, base_dir):
        if "manifest" in args:
            if (
                args.manifest.endswith(".aib")
                or args.manifest.endswith(".aib.yml")
                or args.manifest.endswith(".aib.yaml")
            ):
                args.simple_manifest = args.manifest
                args.manifest = os.path.join(base_dir, "files/simple.mpp.yml")

        self.args = args
        self.base_dir = base_dir

        if args.verbose:
            log.setLevel("DEBUG")

    @cached_property
    def include_dirs(self):
        return [self.base_dir] + self.args.include

    @cached_property
    def build_dir(self):
        return os.path.expanduser(self.args.build_dir) if self.args.build_dir else None

    def _find_policy_path(self, policy_name, search_local=True):
        """Find policy file in search order.

        Args:
            policy_name: Policy filename (with .aibp.yml extension)
            search_local: Whether to search current working directory first

        Returns:
            str: Path to policy file
        """
        search_paths = []

        if search_local:
            search_paths.append(policy_name)  # Current working directory

        # System-wide policies
        search_paths.append(
            os.path.join("/etc/automotive-image-builder/policies", policy_name)
        )
        # Package-provided policies
        search_paths.append(
            os.path.join(self.base_dir, "files", "policies", policy_name)
        )

        for path in search_paths:
            if os.path.exists(path):
                return path

        # Return the last path as fallback (will generate appropriate error)
        return search_paths[-1]

    @cached_property
    def policy(self):
        """Load and cache policy from --policy argument.

        Returns None if no policy is specified, otherwise returns the loaded Policy object.
        Policy loading happens lazily on first access and is cached for subsequent calls.

        Policy resolution:
        - If --policy contains path separators, treat as full path
        - If --policy has no extension, look in installed policy directories:
          1. /etc/automotive-image-builder/policies/ (system-wide)
          2. {base_dir}/files/policies/ (package-provided)
        - If --policy has extension but no separators, try local first, then installed:
          1. Current working directory
          2. /etc/automotive-image-builder/policies/
          3. {base_dir}/files/policies/
        """

        if not self.args.policy:
            return None

        policy_input = self.args.policy

        # If policy input contains path separators, treat as full path
        if os.path.sep in policy_input:
            policy_path = policy_input
        elif not policy_input.endswith(".aibp.yml"):
            # No extension - only look in installed policies (no local search)
            policy_name = policy_input + ".aibp.yml"
            policy_path = self._find_policy_path(policy_name, search_local=False)
        else:
            # Has extension but no separators - search local first, then installed
            policy_path = self._find_policy_path(policy_input, search_local=True)

        try:
            loader = PolicyLoader(self.base_dir)
            return loader.load_policy(Path(policy_path), self.args.target)
        except FileNotFoundError:
            raise PolicyError(f"Policy file not found: {policy_path}")

    def func(self, tmpdir, runner):
        return self.args.func(self, tmpdir, runner)

    def log_file(self, tmpdir):
        if self.args.progress or self.args.logfile:
            build_dir = self.args.build_dir or tmpdir
            filename = f"automotive-image-builder-{time.strftime('%Y%m%d-%H%M%S')}.log"
            return self.args.logfile or os.path.join(build_dir, filename)
        return None

    def __getattr__(self, name: str) -> Any:
        return vars(self.args).get(name)


class CustomFormatter(logging.Formatter):
    def format(self, record):
        log_fmt = logging.Formatter("%(message)s")
        if record.levelno >= logging.WARNING:
            log_fmt = logging.Formatter("%(levelname)s: %(message)s")
        return log_fmt.format(record)


class InfoFilter(logging.Filter):
    def filter(self, record):
        return record.levelno in (logging.DEBUG, logging.INFO)


log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

# create info and debug handler
h1 = logging.StreamHandler(sys.stdout)
h1.setLevel(logging.DEBUG)
h1.setFormatter(CustomFormatter())
h1.addFilter(InfoFilter())
# create handler for the rest
h2 = logging.StreamHandler()
h2.setLevel(logging.WARNING)
h2.setFormatter(CustomFormatter())
# add the handlers to the logger
log.addHandler(h1)
log.addHandler(h2)
