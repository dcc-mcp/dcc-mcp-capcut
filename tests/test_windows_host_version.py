"""Windows host version reading.

Windows is CapCut's primary platform and the one the matrix's acceptance record
was measured on, but discovery used to resolve no more than an ``.exe`` path, so
``host_version`` was always ``None`` and every preflight graded the primary
platform ``undetermined`` -- a warning that never clears, and one that dilutes
the real signal: a build that *was* read and is *not* in the matrix.

Only the Windows lane can exercise the real ``version.dll`` call, so these
tests split in two. A stubbed ``version.dll`` proves the decode -- the
argument marshalling, the signature check and the four-part assembly -- on
every lane, and a small real-Windows section reads a genuine version resource
but skips elsewhere rather than failing or silently passing.
"""

from __future__ import annotations

import ctypes
import os
import re
import sys
from pathlib import Path

import pytest

from dcc_mcp_capcut import doctor
from dcc_mcp_capcut.hosts import get_provider, pe_version
from dcc_mcp_capcut.hosts import windows as windows_host
from dcc_mcp_capcut.hosts.versions import UNDETERMINED, UNKNOWN, VERIFIED, VERIFIED_BUILD

# --------------------------------------------------------------------------
# A version.dll stub, so the decode is exercised on every lane
# --------------------------------------------------------------------------


class _FakeVersionLibrary:
    """Stands in for ``version.dll``: records the calls, hands back canned data.

    The three functions take the same ctypes objects the real call passes, so a
    stub that accepted loose Python values would prove nothing about the
    marshalling that has to survive contact with the real DLL.
    """

    def __init__(
        self,
        *,
        size: int = 1024,
        info: bool = True,
        query: bool = True,
        signature: int = pe_version.FIXED_FILE_INFO_SIGNATURE,
        version: tuple[int, int, int, int] = (9, 4, 0, 4015),
        raises: Exception | None = None,
    ) -> None:
        self.size = size
        self.info = info
        self.query = query
        self.raises = raises
        self.calls: list[tuple[str, object]] = []
        self._fixed = pe_version._FixedFileInfo()
        self._fixed.dwSignature = signature
        self._fixed.dwStrucVersion = 0x00010000
        self._fixed.dwFileVersionMS = (version[0] << 16) | version[1]
        self._fixed.dwFileVersionLS = (version[2] << 16) | version[3]

    def GetFileVersionInfoSizeW(self, path, handle):
        self.calls.append(("size", path.value))
        if self.raises is not None:
            raise self.raises
        return self.size

    def GetFileVersionInfoW(self, path, ignored, length, block):
        self.calls.append(("info", (path.value, length.value, len(block))))
        return 1 if self.info else 0

    def VerQueryValueW(self, block, sub_block, buffer, length):
        self.calls.append(("query", sub_block.value))
        if not self.query:
            return 0
        # ``ctypes.byref`` hands the callee a CArgObject; ``_obj`` is the output
        # cell behind it, which is what the real call would have written to.
        buffer._obj.value = ctypes.cast(ctypes.byref(self._fixed), ctypes.c_void_p).value
        length._obj.value = ctypes.sizeof(pe_version._FixedFileInfo)
        return 1


def test_the_fixed_file_info_decodes_to_the_four_part_build():
    """The acceptance build's own spelling, read out of a version resource."""
    version, stub = _read_stubbed()
    assert version == VERIFIED_BUILD.version
    # The root sub-block is the fixed stamp, not a localisable string table.
    assert [name for name, _ in stub.calls] == ["size", "info", "query"]
    assert stub.calls[2][1] == "\\"


def _read_stubbed(**kwargs) -> tuple[str | None, _FakeVersionLibrary]:
    target = Path(sys.executable)
    stub = _FakeVersionLibrary(**kwargs)
    original = pe_version._load_version_library
    try:
        pe_version._load_version_library = lambda: stub
        return pe_version.read_pe_version(target), stub
    finally:
        pe_version._load_version_library = original


def test_a_file_with_no_version_resource_reads_as_nothing(monkeypatch):
    """No resource block means no version, not an invented one."""
    stub = _FakeVersionLibrary(size=0)
    monkeypatch.setattr(pe_version, "_load_version_library", lambda: stub)
    assert pe_version.read_pe_version(sys.executable) is None
    # A missing resource must not be probed further: there is nothing to query.
    assert [name for name, _ in stub.calls] == ["size"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"info": False},  # GetFileVersionInfoW refused
        {"query": False},  # no root sub-block in the block
        {"signature": 0},  # the block is not a fixed file info
        {"version": (0, 0, 0, 0)},  # resource present, no version stamped
        {"raises": OSError("sharing violation")},  # locked or unreadable file
    ],
    ids=["no-info", "no-query", "bad-signature", "unstamped", "os-error"],
)
def test_every_failure_mode_degrades_to_none(monkeypatch, kwargs):
    """Version metadata is advisory, so none of these may fail discovery."""
    stub = _FakeVersionLibrary(**kwargs)
    monkeypatch.setattr(pe_version, "_load_version_library", lambda: stub)
    assert pe_version.read_pe_version(sys.executable) is None


def test_an_unstamped_resource_is_not_reported_as_a_build(monkeypatch):
    """0.0.0.0 names a build that was never shipped; "unread" is the truth."""
    stub = _FakeVersionLibrary(version=(0, 0, 0, 0))
    monkeypatch.setattr(pe_version, "_load_version_library", lambda: stub)
    assert pe_version.read_pe_version(sys.executable) is None
    # The resource *was* read, so the reader got as far as the query.
    assert [name for name, _ in stub.calls] == ["size", "info", "query"]


def test_no_version_library_means_no_read(monkeypatch):
    """Off Windows there is no version.dll, and nothing is attempted."""
    monkeypatch.setattr(pe_version, "_load_version_library", lambda: None)
    assert pe_version.read_pe_version(sys.executable) is None


# ``Path("")`` is deliberately absent: ``os.fspath`` renders it as ".", a real
# path, so it is not a "cannot name a file" case.
@pytest.mark.parametrize("path", [None, "", "   "])
def test_a_path_that_cannot_name_a_file_is_not_read(monkeypatch, path):
    def explode():
        raise AssertionError("the OS was called with no path")

    monkeypatch.setattr(pe_version, "_load_version_library", explode)
    assert pe_version.read_pe_version(path) is None


# --------------------------------------------------------------------------
# The Windows provider grades what the reader returns
# --------------------------------------------------------------------------


@pytest.fixture
def windows_install(tmp_path, monkeypatch):
    """Materialise an installed Windows host under a temporary LOCALAPPDATA."""
    install = tmp_path / "CapCut" / "Apps"
    install.mkdir(parents=True)
    executable = install / "CapCut.exe"
    executable.write_bytes(b"MZ")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "none"))
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "none2"))
    return executable


def _pin_reader(monkeypatch, version: str | None, calls: list[Path] | None = None):
    def fake(path):
        if calls is not None:
            calls.append(Path(path))
        return version

    monkeypatch.setattr(windows_host, "read_pe_version", fake)


def test_a_read_version_is_graded_instead_of_undetermined(
    pin_platform, monkeypatch, windows_install
):
    """Acceptance: once Windows can read a version, the matrix is no longer inert."""
    pin_platform("windows")
    _pin_reader(monkeypatch, VERIFIED_BUILD.version)

    detection = get_provider().detect_installation()

    assert detection["installed"] is True
    assert detection["host_version"] == VERIFIED_BUILD.version
    support = detection["version_support"]
    assert support["status"] == VERIFIED
    assert support["status"] != UNDETERMINED
    assert support["listed"] is True


def test_an_unlisted_version_is_graded_unknown(pin_platform, monkeypatch, windows_install):
    """A build that was read but is not in the matrix is the real signal."""
    pin_platform("windows")
    _pin_reader(monkeypatch, "9.9.9.9999")

    support = get_provider().detect_installation()["version_support"]

    assert support["status"] == UNKNOWN
    assert support["version"] == "9.9.9.9999"
    assert "9.9.9.9999" in support["hint"]


def test_an_unreadable_version_stays_undetermined_with_a_hint(
    pin_platform, monkeypatch, windows_install
):
    """Acceptance: a version that cannot be read warns, it does not pass silently."""
    pin_platform("windows")
    _pin_reader(monkeypatch, None)

    detection = get_provider().detect_installation()

    assert detection["host_version"] is None
    support = detection["version_support"]
    assert support["status"] == UNDETERMINED
    assert "could not be read" in support["hint"]
    assert VERIFIED_BUILD.version in support["hint"]


def test_the_read_version_reaches_the_doctor_verdict(pin_platform, monkeypatch, windows_install):
    """End to end: the primary platform can now clear the warning."""
    pin_platform("windows")
    _pin_reader(monkeypatch, VERIFIED_BUILD.version)

    check = doctor.check_host_version()

    assert check.status == doctor.OK
    assert check.detail["host_version"] == VERIFIED_BUILD.version
    assert check.hint is None


def test_discovery_reads_the_discovered_executable_once(pin_platform, monkeypatch, windows_install):
    """The version comes from the .exe discovery found, and is not read twice."""
    provider = pin_platform("windows")
    calls: list[Path] = []
    _pin_reader(monkeypatch, VERIFIED_BUILD.version, calls)

    detection = provider.detect_installation()
    provider.host_version()

    # One read for detect_installation, one for the standalone accessor: never a
    # second read inside a single detect_installation() call.
    assert detection["version_support"]["version"] == VERIFIED_BUILD.version
    assert calls == [windows_install, windows_install]


def test_host_version_alone_reads_the_installed_exe(pin_platform, monkeypatch, windows_install):
    """The provider-level accessor is the extension point the matrix consumes."""
    provider = pin_platform("windows")
    calls: list[Path] = []
    _pin_reader(monkeypatch, "6.9.0", calls)

    assert provider.host_version() == "6.9.0"
    assert calls == [windows_install]


# --------------------------------------------------------------------------
# Real Windows only: the one lane with a real version.dll
# --------------------------------------------------------------------------

_VERSION_PATTERN = re.compile(r"\d+(\.\d+){3}")


@pytest.mark.skipif(os.name != "nt", reason="version.dll only exists on Windows")
def test_the_real_reader_reads_a_shipped_version_resource():
    """Windows lane: the actual API call, against a PE image with a stamp."""
    version = pe_version.read_pe_version(sys.executable)
    assert version is not None, f"no version resource in {sys.executable}"
    assert _VERSION_PATTERN.fullmatch(version), version


@pytest.mark.skipif(os.name != "nt", reason="version.dll only exists on Windows")
def test_a_real_capcut_install_grades_for_real(pin_platform):
    """Windows lane with CapCut installed: the primary platform grades a build.

    CI runners have no CapCut, so this proves the claim only where a real host
    exists -- which is exactly the machine the constant warning was hurting.
    """
    provider = pin_platform("windows")
    detection = provider.detect_installation()
    if not detection["installed"]:
        pytest.skip("no CapCut installation on this machine")

    version = detection["host_version"]
    assert version is not None, "an installed CapCut.exe carries no version resource"
    assert _VERSION_PATTERN.fullmatch(version), version
    support = detection["version_support"]
    assert support["version"] == version
    # The whole point of the change: the primary platform no longer reports
    # "could not be read" for an install that is perfectly healthy.
    assert support["status"] != UNDETERMINED, support["hint"]
