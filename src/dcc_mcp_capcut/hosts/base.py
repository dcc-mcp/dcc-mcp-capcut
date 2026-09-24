"""The host-binding contract every platform provider implements.

A provider owns everything that used to be a hard-coded Windows assumption:
where the editor can be installed, how a running instance appears in a window
inventory, what a reviewable install plan looks like, and what the doctor
should report when the host is absent. It also owns the one host-version fact
the support matrix needs: the build actually installed on this machine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .flavors import HostFlavor
from .versions import DOCTOR_STATUS, UNDETERMINED, UNKNOWN, VERIFIED, version_support

#: Sentinel for "the caller did not read a version", kept distinct from an
#: explicitly read ``None``. Without it a provider whose discovery read the
#: plist and found no version would probe the filesystem a second time.
_UNREAD: Any = object()

#: One-line summaries for each support-matrix verdict, filled with the edition,
#: the version and the platform label.
_VERSION_SUMMARY = {
    VERIFIED: "{edition} {version} on {platform} is a verified host build",
    "known": "{edition} {version} on {platform} is listed but not acceptance-verified",
    UNKNOWN: "{edition} {version} on {platform} is not in the verified host matrix",
    UNDETERMINED: (
        "the installed {edition} version on {platform} could not be read, "
        "so it is not in the verified host matrix"
    ),
}


class HostProvider(ABC):
    """Platform-specific host binding for one operating system."""

    #: Stable provider id, reported in doctor output and detection payloads.
    name: str = ""

    #: ``os.name`` value this provider serves.
    platform: str = ""

    #: Human-readable platform label used in summaries and hints.
    label: str = ""

    #: True when ByteDance publishes an official desktop client for the platform.
    supported: bool = True

    #: Why the platform is unsupported; empty on supported platforms.
    unsupported_reason: str = ""

    #: Window-inventory disposition: ``supported`` (probe and fail on error),
    #: ``degraded`` (probe, but a missing CLI is a warning), or ``unsupported``
    #: (no inventory is attempted on this platform).
    window_inventory: str = "unsupported"

    @property
    @abstractmethod
    def flavors(self) -> tuple[HostFlavor, ...]:
        """Every shipped edition this provider can discover."""

    @abstractmethod
    def detect_installation(self) -> dict[str, Any]:
        """Return deterministic, read-only installation evidence."""

    @abstractmethod
    def installation_plan(self) -> dict[str, Any]:
        """Build an operator-facing install/configure/verify plan."""

    @abstractmethod
    def check_executable(self) -> dict[str, Any]:
        """Grade installation evidence into a doctor verdict.

        Returns a mapping with ``status`` (``ok``/``warn``/``fail``/``skip``),
        ``summary``, ``detail`` and ``hint`` keys, kept free of any doctor
        import so providers stay usable on their own.
        """

    @abstractmethod
    def window_binding_hint(self, *, inventory_unavailable: bool) -> str:
        """Remediation text for the ``dcc_cua`` check on this platform."""

    def flavor_by_app_name(self, app_name: str) -> HostFlavor | None:
        """Return the flavour owning this window-inventory process name."""
        return next((flavor for flavor in self.flavors if flavor.matches_process(app_name)), None)

    def host_version(self) -> str | None:
        """The installed host build, or None when this platform cannot read one.

        The default is None, which grades as ``undetermined`` rather than
        "verified": a provider that cannot read a version must never imply the
        running build is one the adapter was actually tested against.
        """
        return None

    def version_evidence(self, edition: str | None, version: str | None = None) -> dict[str, Any]:
        """Additive version facts every ``detect_installation()`` reports.

        Providers merge this into their detection payload so the support-matrix
        verdict travels with the rest of the evidence instead of living only in
        the doctor. Pass ``version`` when discovery already read it -- including
        an explicit ``None`` -- so the version is not probed a second time.
        """
        resolved = self.host_version() if version is _UNREAD else version
        support = version_support(self.name, edition, resolved, platform_supported=self.supported)
        return {"host_version": resolved, "version_support": support}

    def check_host_version(self) -> dict[str, Any]:
        """Grade the discovered host build against the support matrix.

        An unlisted or unreadable build is a warning with a hint, never a
        failure: the adapter binds and starts on it. Only two states skip -- a
        platform with no host at all, and a platform where nothing is installed
        yet, because there is then no build to grade.

        Returns the same ``status``/``summary``/``detail``/``hint`` mapping as
        :meth:`check_executable`.
        """
        detection = self.detect_installation()
        support = dict(detection.get("version_support") or {})
        edition = detection.get("flavor")
        version = support.get("version")
        status = support.get("status", UNDETERMINED)

        if not self.supported:
            return {
                "status": DOCTOR_STATUS.get(status, "skip"),
                "summary": (
                    f"CapCut Desktop is unsupported on {self.label}: {self.unsupported_reason}"
                ),
                "detail": self._version_detail(edition, None, support),
                "hint": support.get("hint"),
            }

        if not detection.get("installed"):
            return {
                "status": "skip",
                "summary": (
                    f"no host installation found on {self.label}; "
                    "the version matrix has no build to grade"
                ),
                "detail": self._version_detail(edition, None, support),
                "hint": None,
            }

        return {
            "status": DOCTOR_STATUS.get(status, "warn"),
            "summary": _VERSION_SUMMARY.get(status, _VERSION_SUMMARY[UNDETERMINED]).format(
                edition=edition or "host",
                version=version or "unknown",
                platform=self.label,
            ),
            "detail": self._version_detail(edition, version, support),
            "hint": support.get("hint"),
        }

    def _version_detail(
        self, edition: str | None, version: str | None, support: dict[str, Any]
    ) -> dict[str, Any]:
        """The machine-readable payload behind a ``host_version`` verdict."""
        return {
            "platform": self.name,
            "edition": edition,
            "host_version": version,
            "version_support": support,
        }


__all__ = ["HostProvider"]
