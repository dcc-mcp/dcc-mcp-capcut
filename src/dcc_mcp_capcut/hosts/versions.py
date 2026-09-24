"""Machine-readable host version support matrix.

CapCut and 剪映专业版 ship many builds across platforms and editions, and only
some of them have been acceptance-tested against this adapter's native Qt
probe. Until this module existed that knowledge was prose
(``native/qt-probe/README.md``), so ``detect_installation()`` reported a host as
simply "found" and an untested build passed without comment.

This module is the one source of truth: a table of
``platform x edition x version`` facts plus the grading function every platform
provider and the doctor share. It is deliberately dependency-free and knows
nothing about the doctor, so providers can import it without a cycle.

Grading is evidence, not a gate. A build that is absent from the matrix is an
explicit ``warn`` with a hint -- the adapter still binds and starts on it -- and
only a platform that ships no host at all is ``skip``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

#: The five verdicts. They are intentionally not doctor statuses: the severity
#: mapping lives with the caller so this module stays importable on its own.
VERIFIED = "verified"  # listed in the matrix and acceptance-tested end to end
KNOWN = "known"  # listed as a shipped build, not acceptance-tested here
UNKNOWN = "unknown"  # discovered, but absent from the matrix
UNDETERMINED = "undetermined"  # discovered, but the version could not be read
UNSUPPORTED = "unsupported"  # the platform ships no host at all

#: How each verdict maps onto the doctor's severity contract. Only a platform
#: with no host is skipped; an unverified build is a warning, because the
#: adapter does run on it and the operator deserves to know it is untested.
DOCTOR_STATUS = {
    VERIFIED: "ok",
    KNOWN: "ok",
    UNKNOWN: "warn",
    UNDETERMINED: "warn",
    UNSUPPORTED: "skip",
}


@dataclass(frozen=True)
class HostVersion:
    """One shipped host build the adapter knows about."""

    platform: str
    edition: str
    version: str
    #: The Qt runtime the build vendors, when known. The native probe loads into
    #: a specific Qt ABI, so this is part of the acceptance record rather than
    #: trivia.
    qt_version: str | None = None
    #: True when the build passed the end-to-end acceptance recorded in
    #: ``native/qt-probe/README.md``.
    verified: bool = False
    notes: str = ""

    @property
    def status(self) -> str:
        """The verdict this entry carries: ``verified`` or merely ``known``."""
        return VERIFIED if self.verified else KNOWN

    @property
    def label(self) -> str:
        """A compact human-readable build label, e.g. ``windows/capcut 9.4.0.4015``."""
        return f"{self.platform}/{self.edition} {self.version}"

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serialisable copy, for doctor and ``verify_installation`` output."""
        return dict(asdict(self))


#: The matrix. Every entry is a build ByteDance has actually shipped; ``notes``
#: records how the acceptance was reached so the row can be re-verified later.
SUPPORTED_HOST_VERSIONS: tuple[HostVersion, ...] = (
    HostVersion(
        platform="windows",
        edition="capcut",
        version="9.4.0.4015",
        qt_version="6.2.2",
        verified=True,
        notes=(
            "Loaded the testability library through a DCC-CUA structured launch "
            "request; a bound live request returned 1,094 objects from the home "
            "window, including application ViewModels, with no tree truncation. "
            "See native/qt-probe/README.md."
        ),
    ),
)

#: Convenience handle for the build acceptance has actually covered so far.
VERIFIED_BUILD = SUPPORTED_HOST_VERSIONS[0]


def normalize_version(value: str | None) -> str:
    """Fold the spellings one build can appear under onto a single string.

    A Windows version resource, a bundle plist and CapCut's own about box do not
    agree on presentation, so a leading ``v`` and surrounding space are stripped
    before comparison. Everything else is compared literally: a build number is
    an identifier, not a number to be ranged.
    """
    text = str(value or "").strip()
    if text[:1].lower() == "v":
        return text[1:].strip()
    return text


def versions_for(platform: str | None, edition: str | None) -> tuple[HostVersion, ...]:
    """Every matrix entry for one platform/edition pair, verified builds first."""
    wanted = (str(platform or "").casefold(), str(edition or "").casefold())
    matches = [
        entry
        for entry in SUPPORTED_HOST_VERSIONS
        if (entry.platform.casefold(), entry.edition.casefold()) == wanted
    ]
    return tuple(sorted(matches, key=lambda entry: (not entry.verified, entry.version)))


def find_version(
    platform: str | None, edition: str | None, version: str | None
) -> HostVersion | None:
    """Return the matrix entry for this exact build, or None when unlisted."""
    normalized = normalize_version(version)
    if not normalized:
        # An empty version is "not read yet", which is a different fact from
        # "read and not listed"; callers must not conflate them.
        return None
    return next(
        (entry for entry in versions_for(platform, edition) if entry.version == normalized),
        None,
    )


def verified_builds() -> tuple[HostVersion, ...]:
    """Every acceptance-tested build, across all platforms and editions."""
    return tuple(entry for entry in SUPPORTED_HOST_VERSIONS if entry.verified)


#: How a provider id is spelled in operator-facing text. ``str.title()`` would
#: render ``macos`` as "Macos", and a hint that misnames the platform is worse
#: than a lookup table.
_PLATFORM_LABELS = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}


def platform_label(platform: str | None) -> str:
    """The operator-facing spelling of a provider id."""
    text = str(platform or "")
    return _PLATFORM_LABELS.get(text.casefold(), text)


def _label(platform: str | None) -> str:
    return platform_label(platform) or "this platform"


def _hint(platform: str | None, edition: str | None, known: list[str]) -> str:
    builds = "; ".join(f"{entry.label} (Qt {entry.qt_version})" for entry in verified_builds())
    scope = ", ".join(known) if known else f"none recorded for {platform}/{edition}"
    return (
        f"Verified builds: {builds or 'none yet'}. Versions listed for "
        f"{platform}/{edition}: {scope}. The adapter still binds and starts on an "
        "unlisted build, but the native Qt probe and window binding are untested "
        "there; record the version so it can be added to the matrix."
    )


def version_support(
    platform: str | None,
    edition: str | None,
    version: str | None,
    *,
    platform_supported: bool = True,
) -> dict[str, Any]:
    """Grade one discovered host build against the matrix.

    The result is machine-readable evidence and never a gate: ``listed`` says
    whether the build appears in the matrix, ``status`` carries the verdict, and
    ``hint`` holds the remediation text. A caller that needs a severity maps
    ``status`` through :data:`DOCTOR_STATUS`.
    """
    normalized = normalize_version(version)
    listed = versions_for(platform, edition)
    known = [entry.version for entry in listed]
    common: dict[str, Any] = {
        "platform": platform,
        "edition": edition,
        "version": normalized or None,
        "known_versions": known,
        "verified_builds": [entry.as_dict() for entry in verified_builds()],
    }

    if not platform_supported:
        return {
            **common,
            "status": UNSUPPORTED,
            "listed": False,
            "match": None,
            "hint": (
                f"CapCut ships no official {_label(platform)} client, so no host "
                "version can be verified on this platform."
            ),
        }

    match = find_version(platform, edition, normalized)
    if match is not None:
        return {
            **common,
            "status": match.status,
            "listed": True,
            "match": match.as_dict(),
            # A listed-but-unverified build still gets a nudge, because "shipped"
            # and "acceptance-tested against this adapter" are different claims.
            "hint": None if match.verified else _hint(platform, edition, known),
        }

    if normalized:
        return {
            **common,
            "status": UNKNOWN,
            "listed": False,
            "match": None,
            "hint": (
                f"{edition} {normalized} on {_label(platform)} is not in the verified "
                f"host matrix. {_hint(platform, edition, known)}"
            ),
        }

    return {
        **common,
        "status": UNDETERMINED,
        "listed": False,
        "match": None,
        "hint": (
            f"The installed {edition} version on {_label(platform)} could not be "
            "read, so this build cannot be matched against the matrix. "
            f"{_hint(platform, edition, known)}"
        ),
    }


__all__ = [
    "DOCTOR_STATUS",
    "KNOWN",
    "SUPPORTED_HOST_VERSIONS",
    "UNDETERMINED",
    "UNKNOWN",
    "UNSUPPORTED",
    "VERIFIED",
    "VERIFIED_BUILD",
    "HostVersion",
    "find_version",
    "normalize_version",
    "platform_label",
    "verified_builds",
    "version_support",
    "versions_for",
]
