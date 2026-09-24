"""Linux host binding: explicitly unsupported, never silently degraded.

ByteDance publishes no official CapCut or 剪映 professional client for Linux.
Reporting "not installed" there would invite an operator to hunt for a package
that does not exist; reporting success would be a lie. This provider states the
conclusion once, with the reason, and every consumer echoes it.
"""

from __future__ import annotations

import os
from typing import Any

from .base import HostProvider
from .flavors import HostFlavor

UNSUPPORTED_REASON = (
    "CapCut and 剪映专业版 ship no official Linux client; the adapter has no "
    "host to bind on this platform."
)

SUPPORTED_PLATFORMS = ("Windows", "macOS")


class LinuxHostProvider(HostProvider):
    """Linux: no official client exists, so nothing is discovered or planned."""

    name = "linux"
    platform = "posix"
    label = "Linux"
    supported = False
    unsupported_reason = UNSUPPORTED_REASON
    window_inventory = "unsupported"

    @property
    def flavors(self) -> tuple[HostFlavor, ...]:
        return ()

    def detect_installation(self) -> dict[str, Any]:
        return {
            "installed": False,
            "executable": None,
            "app_bundle": None,
            "flavor": None,
            "candidates_checked": [],
            "package_id": None,
            "platform": os.name,
            "provider": self.name,
            "supported": False,
            "unsupported": True,
            "reason": UNSUPPORTED_REASON,
            # No host ships for this platform, so there is no build to grade;
            # the matrix reports that explicitly instead of staying silent.
            **self.version_evidence(None),
        }

    def installation_plan(self) -> dict[str, Any]:
        detection = self.detect_installation()
        return {
            "status": "unsupported",
            "detection": detection,
            "installer": None,
            "environment": {
                "DCC_MCP_CAPCUT_BRIDGE_PORT": os.environ.get("DCC_MCP_CAPCUT_BRIDGE_PORT", "47410"),
                "DCC_MCP_CAPCUT_BRIDGE_TOKEN": "<generate-per-user-secret>",
                "DCC_MCP_CAPCUT_WINDOW_TITLE": "CapCut",
                "DCC_MCP_CAPCUT_INSTANCE_TYPE": "gui",
            },
            "post_install": [],
            "next_step": (
                "Run the adapter on a Windows or macOS host that owns the CapCut "
                "window; no install plan exists for Linux."
            ),
            "supported_platforms": list(SUPPORTED_PLATFORMS),
        }

    def check_executable(self) -> dict[str, Any]:
        return {
            "status": "skip",
            "summary": f"CapCut Desktop is unsupported on {self.label}: {UNSUPPORTED_REASON}",
            "detail": {
                **self.detect_installation(),
                "supported_platforms": list(SUPPORTED_PLATFORMS),
            },
            "hint": (
                "Run the adapter on a Windows or macOS host that owns the CapCut "
                "window; the bridge, panel and window binding all target that host."
            ),
        }

    def window_binding_hint(self, *, inventory_unavailable: bool = True) -> str:
        _ = inventory_unavailable
        return (
            f"CapCut window binding is unsupported on {self.label}: {UNSUPPORTED_REASON} "
            f"Supported platforms: {', '.join(SUPPORTED_PLATFORMS)}."
        )


__all__ = ["SUPPORTED_PLATFORMS", "UNSUPPORTED_REASON", "LinuxHostProvider"]
