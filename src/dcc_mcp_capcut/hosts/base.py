"""The host-binding contract every platform provider implements.

A provider owns everything that used to be a hard-coded Windows assumption:
where the editor can be installed, how a running instance appears in a window
inventory, what a reviewable install plan looks like, and what the doctor
should report when the host is absent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .flavors import HostFlavor


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


__all__ = ["HostProvider"]
