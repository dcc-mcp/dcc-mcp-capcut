"""Version guard and install-tree snapshot.

Pixel automation is only valid against the build it was measured on, so the
version guard is stricter here than the doctor is: the doctor warns on an
unlisted build because the adapter still *starts* on one, while execution refuses
because a coordinate nobody measured is not a coordinate that lands.

The install-tree half covers the failure the spike measured in the wild: a
CapCut 9.5.0.4050 launch deleted the 9.4.0.4015 install directory it replaced.
An install tree is therefore not a stable fact, and a snapshot taken before
launch has to be diffable afterwards.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from dcc_mcp_capcut.cua import guards
from dcc_mcp_capcut.cua.errors import CuaError
from dcc_mcp_capcut.hosts import LINUX, MACOS, WINDOWS, get_provider


@pytest.fixture
def windows(pin_platform):
    return pin_platform(WINDOWS)


def _write_install(root: Path, *, flavour: str = "CapCut", version: str = "9.4.0.4015") -> Path:
    """Materialise a Windows-shaped install tree under ``root``.

    The ``.exe`` is a placeholder, not a real PE image, so the version is
    supplied by patching the reader. These tests are about what the *guard* does
    with a version, not about PE parsing -- that is covered in
    ``test_windows_host_version.py``.
    """
    tree = root / flavour / "Apps"
    tree.mkdir(parents=True)
    (tree / f"{flavour}.exe").write_bytes(b"MZ" + version.encode())
    (tree / "resources.pak").write_bytes(b"pak")
    return tree / f"{flavour}.exe"


@pytest.fixture
def installed_version(monkeypatch):
    """Pin the build the Windows provider reports, without a real PE image."""

    def _pin(version: str | None):
        import dcc_mcp_capcut.hosts.windows as windows_host

        monkeypatch.setattr(windows_host, "read_pe_version", lambda path: version)
        return version

    return _pin


# --- version guard ---------------------------------------------------------


def test_a_verified_build_is_pinned(windows, tmp_path, monkeypatch, installed_version):
    """A listed build is one coordinates may be measured against."""
    _write_install(tmp_path, version="9.4.0.4015")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    installed_version("9.4.0.4015")
    guard = guards.guard_host_version()
    assert guard.status == guards.PINNED
    assert guard.allowed is True
    assert guard.version == "9.4.0.4015"


def test_a_live_driven_build_is_pinned_even_without_acceptance(
    windows, tmp_path, monkeypatch, installed_version
):
    """9.5.0.4050 was driven live, so it is listed -- pinned, though unverified."""
    _write_install(tmp_path, version="9.5.0.4050")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    installed_version("9.5.0.4050")
    guard = guards.guard_host_version()
    assert guard.status == guards.PINNED
    assert guard.allowed is True
    assert guard.version == "9.5.0.4050"


def test_an_unlisted_build_is_unpinned_and_refused(
    windows, tmp_path, monkeypatch, installed_version
):
    """An unrecorded build is one nobody measured coordinates on."""
    _write_install(tmp_path, version="10.9.9.9999")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    installed_version("10.9.9.9999")
    guard = guards.guard_host_version()
    assert guard.status == guards.UNPINNED
    assert guard.allowed is False
    assert "not in the verified host matrix" in guard.hint


def test_an_unpinned_build_can_be_run_only_by_explicit_opt_in(
    windows, tmp_path, monkeypatch, installed_version
):
    """``allow_unverified`` is an acknowledgement, not a default."""
    _write_install(tmp_path, version="10.9.9.9999")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    installed_version("10.9.9.9999")
    assert guards.guard_host_version(allow_unverified=True).allowed is True
    assert guards.guard_host_version().allowed is False


def test_guard_reports_no_host_rather_than_grading_nothing(windows, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    guard = guards.guard_host_version()
    assert guard.status == guards.NO_HOST
    assert guard.allowed is False


def test_guard_skips_an_unsupported_platform(pin_platform):
    provider = pin_platform(LINUX)
    guard = guards.guard_host_version(platform=LINUX)
    assert guard.status == guards.UNSUPPORTED_PLATFORM
    assert guard.allowed is False
    assert provider.name == LINUX


def test_the_guard_verdict_is_machine_readable(windows, tmp_path, monkeypatch, installed_version):
    """A receipt has to be serialisable, so it goes in a report and a log."""
    _write_install(tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    installed_version("9.5.0.4050")
    payload = guards.guard_host_version().as_dict()
    assert set(payload) >= {"status", "edition", "version", "allowed", "hint"}
    assert isinstance(payload["allowed"], bool)


# --- install tree ----------------------------------------------------------


def test_the_install_root_is_the_flavour_directory_not_the_binary(windows, tmp_path, monkeypatch):
    """Windows nests the binary under ``<app>/Apps``; the tree is the root."""
    _write_install(tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert guards.install_root() == tmp_path / "CapCut"


def test_a_snapshot_fingerprints_the_tree(windows, tmp_path):
    _write_install(tmp_path)
    snap = guards.snapshot_install_tree(tmp_path / "CapCut")
    assert snap.exists is True
    assert snap.file_count == 2
    assert snap.total_bytes > 0
    assert len(snap.digest) == 64


def test_two_snapshots_of_an_unchanged_tree_are_identical(windows, tmp_path):
    _write_install(tmp_path)
    root = tmp_path / "CapCut"
    assert guards.snapshot_install_tree(root).digest == guards.snapshot_install_tree(root).digest


def test_a_missing_tree_is_a_result_not_an_error(windows, tmp_path):
    """'The install is gone' is exactly what this snapshot exists to record."""
    snap = guards.snapshot_install_tree(tmp_path / "nope")
    assert snap.exists is False
    assert snap.file_count == 0
    assert snap.digest == ""


def test_a_changed_file_shows_up_as_changed(windows, tmp_path):
    _write_install(tmp_path)
    root = tmp_path / "CapCut"
    before = guards.snapshot_install_tree(root)
    (root / "Apps" / "resources.pak").write_bytes(b"different")
    diff = guards.diff_install_tree(before, guards.snapshot_install_tree(root))
    assert diff.changed == ("Apps/resources.pak",)
    assert not diff.unchanged


def test_an_added_file_shows_up_as_added(windows, tmp_path):
    _write_install(tmp_path)
    root = tmp_path / "CapCut"
    before = guards.snapshot_install_tree(root)
    (root / "Apps" / "new.dll").write_bytes(b"dll")
    diff = guards.diff_install_tree(before, guards.snapshot_install_tree(root))
    assert diff.added == ("Apps/new.dll",)
    assert diff.removed == ()


def test_the_observed_self_upgrade_is_reported_as_a_host_replacement(windows, tmp_path):
    """CapCut 9.5.0.4050 deleted the 9.4.0.4015 tree it replaced.

    A binding taken before that event names a process that no longer exists, so
    the diff has to say "the host was replaced" rather than "some files moved".
    """
    _write_install(tmp_path)
    root = tmp_path / "CapCut"
    before = guards.snapshot_install_tree(root)
    shutil.rmtree(root)
    diff = guards.diff_install_tree(before, guards.snapshot_install_tree(root))
    assert diff.host_replaced is True
    assert not diff.unchanged


def test_a_vanished_install_marks_the_host_replaced(windows, tmp_path):
    _write_install(tmp_path)
    before = guards.snapshot_install_tree(tmp_path / "CapCut")
    after = guards.snapshot_install_tree(tmp_path / "elsewhere")
    diff = guards.diff_install_tree(before, after)
    assert diff.host_replaced is True


def test_different_roots_mean_the_install_moved_not_drifted(windows, tmp_path):
    """Two unrelated roots are not a diff; asserting one would be a lie."""
    _write_install(tmp_path / "one")
    _write_install(tmp_path / "two")
    before = guards.snapshot_install_tree(tmp_path / "one")
    after = guards.snapshot_install_tree(tmp_path / "two")
    diff = guards.diff_install_tree(before, after)
    assert diff.added == () and diff.removed == () and diff.changed == ()


def test_a_snapshot_is_deterministic_regardless_of_walk_order(windows, tmp_path):
    """The digest is over sorted entries, so it is stable across runs."""
    _write_install(tmp_path)
    root = tmp_path / "CapCut"
    digests = {guards.snapshot_install_tree(root).digest for _ in range(3)}
    assert len(digests) == 1


def test_the_guard_captures_and_rechecks_the_same_root(windows, tmp_path):
    _write_install(tmp_path)
    root = tmp_path / "CapCut"
    guard = guards.InstallTreeGuard.capture(root=root)
    assert guard.recheck().unchanged is True
    (root / "Apps" / "extra.bin").write_bytes(b"x")
    assert guard.recheck().added == ("Apps/extra.bin",)


def test_the_walk_is_bounded_so_preflight_stays_fast(windows, tmp_path, monkeypatch):
    """An install tree can hold tens of thousands of files; cap it and say so."""
    monkeypatch.setattr(guards, "MAX_FILES", 3)
    _write_install(tmp_path)
    root = tmp_path / "CapCut"
    for index in range(10):
        (root / "Apps" / f"file{index}.bin").write_bytes(b"x")
    snap = guards.snapshot_install_tree(root)
    assert snap.file_count == 3
    assert snap.truncated is True


def test_paths_are_recorded_portably(windows, tmp_path):
    """Backslashes would make two identical trees hash differently by OS."""
    _write_install(tmp_path)
    snap = guards.snapshot_install_tree(tmp_path / "CapCut")
    assert all("\\" not in name for name, _, _ in snap.entries)


def test_a_macos_bundle_is_its_own_install_root(
    pin_platform, tmp_path, monkeypatch, macos_applications
):
    """On macOS the tree that matters is the ``.app`` bundle, not the binary."""
    provider = pin_platform(MACOS)
    bundle = macos_applications("CapCut.app", version="6.9.0")
    (bundle / "Contents" / "Resources" / "app.pak").parent.mkdir(parents=True, exist_ok=True)
    (bundle / "Contents" / "Resources" / "app.pak").write_bytes(b"pak")
    assert provider.name == MACOS
    assert guards.install_root(platform=MACOS) == bundle


def test_the_tree_snapshot_survives_a_file_vanishing_mid_walk(windows, tmp_path):
    """An installer can replace a file between listing and stat."""
    _write_install(tmp_path)
    root = tmp_path / "CapCut"
    real_stat = os.stat

    def flaky_stat(path, **kwargs):
        if str(path).endswith("resources.pak"):
            raise OSError("gone")
        return real_stat(path, **kwargs)

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(Path, "stat", lambda self, **kwargs: flaky_stat(self, **kwargs))
        snap = guards.snapshot_install_tree(root)
    finally:
        monkeypatch.undo()
    assert snap.exists is True
    assert [name for name, _, _ in snap.entries] == ["Apps/CapCut.exe"]


# --- the guard pair --------------------------------------------------------


def test_bind_and_check_refuses_an_unpinned_build(
    windows, tmp_path, monkeypatch, installed_version
):
    """Binding without grading would hold an exact PID for the wrong build."""
    from dcc_mcp_capcut import cua

    _write_install(tmp_path, version="10.9.9.9999")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    installed_version("10.9.9.9999")
    with pytest.raises(CuaError, match="refusing to run pixel execution"):
        cua.bind_and_check()


def test_bind_and_check_returns_both_facts(windows, tmp_path, monkeypatch, installed_version):
    """The guarded entry point hands back the binding *and* the verdict."""
    from dcc_mcp_capcut import cua

    _write_install(tmp_path, version="9.5.0.4050")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    installed_version("9.5.0.4050")
    monkeypatch.setattr(cua, "bind", lambda **kwargs: cua.CuaBinding(pid=1, window_handle=2))
    binding, guard = cua.bind_and_check()
    assert binding.pid == 1
    assert guard.status == guards.PINNED


def test_get_provider_defaults_to_the_running_platform():
    """Guards a regression: the guard must not silently grade another platform."""
    assert get_provider().name in {WINDOWS, MACOS, LINUX}


def test_different_roots_are_a_replacement_not_a_clean_diff(windows, tmp_path):
    """An install that moved is not 'unchanged' -- the binding is invalid either way."""
    _write_install(tmp_path / "one")
    _write_install(tmp_path / "two")
    before = guards.snapshot_install_tree(tmp_path / "one")
    after = guards.snapshot_install_tree(tmp_path / "two")
    diff = guards.diff_install_tree(before, after)
    assert diff.roots_match is False
    assert diff.unchanged is False
    # A moved install invalidates the binding just as a deleted one does.
    assert diff.host_replaced is True


def test_roots_match_reports_the_same_root_as_matching(windows, tmp_path):
    _write_install(tmp_path)
    root = tmp_path / "CapCut"
    diff = guards.diff_install_tree(
        guards.snapshot_install_tree(root), guards.snapshot_install_tree(root)
    )
    assert diff.roots_match is True
    assert diff.unchanged is True


def test_a_single_file_tree_with_nothing_removed_is_not_a_replacement(windows, tmp_path):
    """A majority threshold of zero would call an untouched tree 'replaced'."""
    tree = tmp_path / "CapCut" / "Apps"
    tree.mkdir(parents=True)
    (tree / "CapCut.exe").write_bytes(b"MZ")
    root = tmp_path / "CapCut"
    snapshot = guards.snapshot_install_tree(root)
    assert snapshot.file_count == 1
    diff = guards.diff_install_tree(snapshot, snapshot)
    assert diff.host_replaced is False


def test_a_single_file_tree_whose_file_vanished_is_a_replacement(windows, tmp_path):
    tree = tmp_path / "CapCut" / "Apps"
    tree.mkdir(parents=True)
    (tree / "CapCut.exe").write_bytes(b"MZ")
    root = tmp_path / "CapCut"
    before = guards.snapshot_install_tree(root)
    (tree / "CapCut.exe").unlink()
    assert (
        guards.diff_install_tree(before, guards.snapshot_install_tree(root)).host_replaced is True
    )


def test_host_replaced_needs_a_strict_majority_removed(windows, tmp_path):
    """Losing a minority of files is drift, not a replaced install."""
    _write_install(tmp_path)
    root = tmp_path / "CapCut"
    before = guards.snapshot_install_tree(root)
    (root / "Apps" / "resources.pak").unlink()
    diff = guards.diff_install_tree(before, guards.snapshot_install_tree(root))
    assert diff.removed == ("Apps/resources.pak",)
    assert diff.host_replaced is False
