"""The machine-readable host version support matrix.

The matrix used to be prose in ``native/qt-probe/README.md``, so an untested
build passed ``detect_installation()`` without comment. These tests pin the
table itself, the grading it produces, and the two consumers that must not
silently pass an unlisted build: ``detect_installation()`` evidence and the
doctor's ``host_version`` check.
"""

from __future__ import annotations

import json

import pytest

from dcc_mcp_capcut import doctor
from dcc_mcp_capcut.hosts import (
    SUPPORTED_HOST_VERSIONS,
    VERIFIED_BUILD,
    find_version,
    get_provider,
    normalize_version,
    version_support,
    versions_for,
)
from dcc_mcp_capcut.hosts import macos as macos_host
from dcc_mcp_capcut.hosts.versions import KNOWN, UNDETERMINED, UNKNOWN, UNSUPPORTED, VERIFIED


def test_the_acceptance_record_is_in_the_matrix():
    """The one build acceptance covered is machine-readable, not just prose."""
    verified = [entry for entry in SUPPORTED_HOST_VERSIONS if entry.verified]
    assert verified == [VERIFIED_BUILD]
    assert (VERIFIED_BUILD.platform, VERIFIED_BUILD.edition) == ("windows", "capcut")
    assert VERIFIED_BUILD.version == "9.4.0.4015"
    assert VERIFIED_BUILD.qt_version == "6.2.2"
    # The acceptance record has to name how it was reached, or it cannot be
    # re-verified later.
    assert "testability" in VERIFIED_BUILD.notes
    assert "qt-probe/README.md" in VERIFIED_BUILD.notes
    assert VERIFIED_BUILD.status == VERIFIED


def test_the_matrix_is_keyed_by_platform_edition_and_version():
    """Every row is addressable, so a provider can ask for its own builds only."""
    for entry in SUPPORTED_HOST_VERSIONS:
        assert entry.platform and entry.edition and entry.version
        assert versions_for(entry.platform, entry.edition) == (entry,)
    assert versions_for("windows", "jianyingpro") == ()
    assert versions_for("macos", "capcut") == ()


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("9.4.0.4015", "9.4.0.4015"),
        ("v9.4.0.4015", "9.4.0.4015"),
        ("  V9.4.0.4015 ", "9.4.0.4015"),
        ("", ""),
        (None, ""),
    ],
)
def test_version_spellings_fold_onto_one_string(raw, expected):
    """A version resource, a plist and an about box disagree on presentation."""
    assert normalize_version(raw) == expected


def test_a_verified_build_is_listed_without_a_hint():
    support = version_support("windows", "capcut", VERIFIED_BUILD.version)
    assert support["status"] == VERIFIED
    assert support["listed"] is True
    assert support["match"]["qt_version"] == "6.2.2"
    assert support["hint"] is None
    assert VERIFIED_BUILD.version in support["known_versions"]


def test_a_shipped_but_unverified_build_warns(pin_platform, monkeypatch):
    """'Shipped' and 'acceptance-tested against this adapter' are different claims."""
    unverified = VERIFIED_BUILD.__class__(
        platform="windows", edition="capcut", version="9.5.0.1000", verified=False
    )
    monkeypatch.setattr(
        "dcc_mcp_capcut.hosts.versions.SUPPORTED_HOST_VERSIONS", (VERIFIED_BUILD, unverified)
    )
    support = version_support("windows", "capcut", "9.5.0.1000")
    assert support["status"] == KNOWN
    assert support["listed"] is True
    assert support["hint"]


def test_an_unlisted_build_is_reported_not_silently_passed():
    support = version_support("windows", "capcut", "9.9.9.9999")
    assert support["status"] == UNKNOWN
    assert support["listed"] is False
    assert support["match"] is None
    hint = support["hint"]
    assert "9.9.9.9999" in hint
    assert VERIFIED_BUILD.version in hint
    # The verdict must not be read as "installation failed".
    assert "still binds and starts" in hint


def test_an_unreadable_version_is_undetermined_not_unknown():
    """'Not read yet' is a different fact from 'read and not listed'."""
    for blank in (None, "", "   "):
        support = version_support("windows", "capcut", blank)
        assert support["status"] == UNDETERMINED, blank
        assert support["listed"] is False
        assert support["hint"]
        assert "could not be read" in support["hint"]


def test_an_unsupported_platform_reports_a_conclusion():
    support = version_support("linux", None, None, platform_supported=False)
    assert support["status"] == UNSUPPORTED
    assert support["listed"] is False
    assert "no official linux client" in support["hint"].lower()


def test_find_version_is_exact_and_never_matches_a_blank():
    assert find_version("windows", "capcut", VERIFIED_BUILD.version) == VERIFIED_BUILD
    assert find_version("windows", "capcut", "v9.4.0.4015") == VERIFIED_BUILD
    assert find_version("windows", "capcut", "9.4.0.4016") is None
    assert find_version("macos", "capcut", VERIFIED_BUILD.version) is None
    assert find_version("windows", "capcut", "") is None


def test_the_verdict_is_json_serialisable():
    """The doctor emits this with ``--json``, so it must contain no Path or set."""
    payload = version_support("windows", "capcut", "9.9.9.9999")
    assert json.loads(json.dumps(payload)) == payload


# --------------------------------------------------------------------------
# detect_installation carries the verdict, so it is not doctor-only
# --------------------------------------------------------------------------


@pytest.mark.parametrize("platform", ["windows", "macos", "linux"])
def test_every_provider_reports_version_evidence(pin_platform, monkeypatch, platform):
    pin_platform(platform)
    detection = get_provider().detect_installation()
    assert "host_version" in detection
    support = detection["version_support"]
    assert support["status"] in {VERIFIED, KNOWN, UNKNOWN, UNDETERMINED, UNSUPPORTED}
    assert "hint" in support
    assert json.loads(json.dumps(detection)) == detection


def test_windows_reports_the_version_as_undetermined(pin_platform, monkeypatch, tmp_path):
    """An .exe carrying no version resource degrades; no version is invented."""
    install = tmp_path / "CapCut" / "Apps"
    install.mkdir(parents=True)
    (install / "CapCut.exe").write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "none"))
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "none2"))
    pin_platform("windows")

    detection = get_provider().detect_installation()

    assert detection["installed"] is True
    assert detection["host_version"] is None
    assert detection["version_support"]["status"] == UNDETERMINED
    assert detection["version_support"]["hint"]


def test_macos_grades_the_bundle_version(pin_platform, macos_applications):
    """The plist is the only version evidence macOS exposes, and it is used."""
    macos_applications("CapCut.app", version="6.9.0")
    pin_platform("macos")

    detection = get_provider().detect_installation()

    assert detection["host_version"] == "6.9.0"
    support = detection["version_support"]
    assert support["version"] == "6.9.0"
    assert support["status"] == UNKNOWN
    assert support["listed"] is False


def test_macos_degrades_to_undetermined_on_an_unreadable_plist(pin_platform, macos_applications):
    macos_applications("CapCut.app", version=None)
    pin_platform("macos")

    detection = get_provider().detect_installation()

    assert detection["installed"] is True
    assert detection["host_version"] is None
    assert detection["version_support"]["status"] == UNDETERMINED


def test_host_version_reads_the_bundle_plist(pin_platform, macos_applications):
    """The provider-level accessor and detection agree on the same fact."""
    macos_applications("JianyingPro.app", version="6.8.0")
    provider = pin_platform("macos")
    assert provider.host_version() == "6.8.0"


# --------------------------------------------------------------------------
# doctor grading
# --------------------------------------------------------------------------


def _patch_detection(monkeypatch, provider, **detection):
    monkeypatch.setattr(type(provider), "detect_installation", lambda _self: dict(detection))


def test_the_check_is_registered():
    assert "host_version" in [name for name, _ in doctor.CHECKS]


def test_check_okays_a_verified_build(pin_platform, monkeypatch):
    provider = pin_platform("windows")
    _patch_detection(
        monkeypatch,
        provider,
        installed=True,
        flavor="capcut",
        host_version=VERIFIED_BUILD.version,
        version_support=version_support("windows", "capcut", VERIFIED_BUILD.version),
    )

    check = doctor.check_host_version()

    assert check.status == doctor.OK
    assert VERIFIED_BUILD.version in check.summary
    assert check.detail["host_version"] == VERIFIED_BUILD.version
    assert check.hint is None


def test_check_warns_on_an_unlisted_build_with_a_hint(pin_platform, monkeypatch):
    """Acceptance: an unlisted version must be named, not silently passed."""
    provider = pin_platform("windows")
    support = version_support("windows", "capcut", "9.9.9.9999")
    _patch_detection(
        monkeypatch,
        provider,
        installed=True,
        flavor="capcut",
        host_version="9.9.9.9999",
        version_support=support,
    )

    check = doctor.check_host_version()

    assert check.status == doctor.WARN
    assert "9.9.9.9999" in check.summary
    assert "not in the verified host matrix" in check.summary
    assert check.hint == support["hint"]
    # A warning, never a failure: the adapter still runs on this build.
    assert check.status != doctor.FAIL


def test_check_warns_when_windows_cannot_read_the_version(pin_platform, monkeypatch, tmp_path):
    """The real Windows path, end to end: installed, but no version to grade."""
    install = tmp_path / "CapCut" / "Apps"
    install.mkdir(parents=True)
    (install / "CapCut.exe").write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "none"))
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "none2"))
    pin_platform("windows")

    check = doctor.check_host_version()

    assert check.status == doctor.WARN
    assert check.detail["host_version"] is None
    assert check.detail["version_support"]["status"] == UNDETERMINED
    assert check.hint


def test_check_skips_when_no_host_is_installed(pin_platform, monkeypatch):
    """With nothing installed there is no build to grade, and no hint to give."""
    provider = pin_platform("windows")
    _patch_detection(monkeypatch, provider, installed=False, flavor="capcut")

    check = doctor.check_host_version()

    assert check.status == doctor.SKIP
    assert "no host installation" in check.summary
    assert check.hint is None


def test_check_skips_on_an_unsupported_platform(pin_platform):
    pin_platform("linux")
    check = doctor.check_host_version()
    assert check.status == doctor.SKIP
    assert check.detail["version_support"]["status"] == UNSUPPORTED
    assert check.hint


def test_check_survives_a_provider_that_reports_no_version_evidence(pin_platform, monkeypatch):
    """A monkeypatched or future provider must degrade to a verdict, not a KeyError."""
    provider = pin_platform("macos")
    _patch_detection(monkeypatch, provider, installed=True, flavor="capcut")

    check = doctor.check_host_version()

    assert check.status in doctor.STATUSES
    assert check.detail["edition"] == "capcut"


def test_a_provider_that_omits_the_version_is_probed(pin_platform, monkeypatch):
    """The extension point: implement ``host_version()``, omit the argument.

    ``version_evidence`` must fall back to ``host_version()`` when no version
    is passed, and what it returns has to take part in the grading. With a
    ``None`` default this branch was unreachable, so such a provider reported
    ``undetermined`` forever and the matrix was inert for it -- which matters
    because the roadmap adds macOS and 剪映专业版 rows to the matrix.
    """
    provider = pin_platform("windows")
    calls = []
    monkeypatch.setattr(
        type(provider), "host_version", lambda _self: calls.append(1) or VERIFIED_BUILD.version
    )

    evidence = provider.version_evidence("capcut")

    assert len(calls) == 1
    assert evidence["host_version"] == VERIFIED_BUILD.version
    assert evidence["version_support"]["status"] == VERIFIED
    assert evidence["version_support"]["listed"] is True


def test_the_probed_version_reaches_the_doctor_verdict(pin_platform, monkeypatch):
    """End-to-end pin: a provider that only implements ``host_version()`` grades for real."""
    provider = pin_platform("windows")
    monkeypatch.setattr(type(provider), "host_version", lambda _self: VERIFIED_BUILD.version)
    monkeypatch.setattr(
        type(provider),
        "detect_installation",
        lambda _self: {
            "installed": True,
            "flavor": "capcut",
            **_self.version_evidence("capcut"),
        },
    )

    check = doctor.check_host_version()

    assert check.status == doctor.OK
    assert check.detail["host_version"] == VERIFIED_BUILD.version
    assert check.detail["version_support"]["listed"] is True


@pytest.mark.parametrize("version", ["6.9.0", None])
def test_macos_reads_the_bundle_plist_exactly_once(
    pin_platform, macos_applications, monkeypatch, version
):
    """Discovery must not re-probe the plist, whatever the plist says.

    A missing ``CFBundleShortVersionString`` is a read that returned nothing,
    not a read that never happened, so it must not trigger a second discovery.
    """
    macos_applications("CapCut.app", version=version)
    provider = pin_platform("macos")
    calls = []
    original = macos_host._read_bundle_metadata

    def counting(bundle):
        calls.append(bundle)
        return original(bundle)

    monkeypatch.setattr(macos_host, "_read_bundle_metadata", counting)

    provider.detect_installation()

    assert len(calls) == 1
