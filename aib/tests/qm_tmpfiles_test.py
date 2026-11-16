"""Initialize QM state on the host after mounting and before starting Podman."""

import importlib.machinery
import importlib.util
from pathlib import Path
import sys
from unittest import mock

from . import mpp_lockfile_test

mpp_module = mpp_lockfile_test.mpp_module

ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    path = ROOT / "files" / name
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.object(sys, "path", [str(path.parent), *sys.path]):
        loader.exec_module(module)
    return module


ostree = load_script("ostree_split_qm_tmpfiles")
shared = sys.modules["aib_postprocess"]


def write(root, path, contents):
    path = root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    return path


def test_split_preserves_mountpoint_siblings_and_rule_arguments():
    host = [
        "# generated\n",
        "\n",
        "; comment\n",
        "d /var/qm 0755 qm_root qm_root - -\n",
        "d /var/qm-other 0755 root root - -\n",
    ]
    moved = [
        '  d+ "/var/qm/a space" 02750 root root 10d -\n',
        r"L /var/qm/link - - - - ../a\x20space" + "\n",
        "L /var/qm/log - - - - /var/log\n",
        r"d /var/\x71m/100%% 0755 root root - -" + "\n",
        "d /var/qm/%m 0700 root root - -\n",
    ]
    host_rules, qm_rules = shared.split_qm_tmpfiles(host + moved)
    assert host_rules == host
    assert qm_rules == [host[3], *moved]


def test_user_namespace_owners_remain_in_host_namespace():
    host = "d /var/qm 0755 qm_root qm_root - -\n"
    entries = [
        host,
        "d /var/qm/named 0750 qm_app qm_app - -\n",
        "d /var/qm/numeric 0700 1000000123 1100000456 - -\n",
        "d /var/qm/other 0755 999 999 - -\n",
    ]
    assert shared.split_qm_tmpfiles(entries) == (
        [host],
        entries,
    )


def test_ostree_without_qm_rules_leaves_source_unchanged(tmp_path):
    source = write(
        tmp_path,
        f"usr/lib/tmpfiles.d/{ostree.AUTOVAR}",
        "d /var/host 0755 root root - -\n",
    )
    original_mtime = source.stat().st_mtime_ns
    ostree.split_autovar(tmp_path)
    assert source.stat().st_mtime_ns == original_mtime
    assert not (tmp_path / "usr/lib/qm").exists()


def test_ostree_mountpoint_rule_also_initializes_fresh_filesystem_root(tmp_path):
    rule = "d /var/qm 0755 qm_root qm_root - -\n"
    source = write(tmp_path, f"usr/lib/tmpfiles.d/{ostree.AUTOVAR}", rule)
    ostree.split_autovar(tmp_path)
    assert source.read_text() == rule
    assert (tmp_path / shared.QM_VAR_TMPFILES).read_text() == rule
