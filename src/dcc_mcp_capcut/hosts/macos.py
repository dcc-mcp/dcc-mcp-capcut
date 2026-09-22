"""macOS host binding: 剪映专业版 / CapCut as ``.app`` bundles.

ByteDance publishes macOS desktop builds as ordinary application bundles, so
discovery is a bundle lookup instead of an ``.exe`` lookup: ``/Applications``
and ``~/Applications`` are searched for ``JianyingPro.app`` and ``CapCut.app``,
and the bundle's ``Contents/Info.plist`` supplies the version evidence the
doctor reports.

Installation is *never* performed. The plan offers only reviewable options --
a Homebrew cask command where one exists, and the official download page for
both editions -- and still travels through the operator-owned
``ui_control__system_operation`` grant.
"""

from __future__ import annotations

import os
import plistlib
from pathlib import Path
from typing import Any
from xml.parsers.expat import ExpatError

from .base import HostProvider
from .flavors import HostFlavor, _existing

#: The two roots macOS searches for user-visible applications.
APPLICATION_ROOTS = ("/Applications", "~/Applications")

#: Homebrew is only a plan suggestion; the adapter never runs it.
HOMEBREW_CASK_COMMAND = "brew install --cask"

ACCESSIBILITY_NOTE = (
    "macOS window binding needs Accessibility permission for the controlling "
    "app (System Settings > Privacy & Security > Accessibility); the adapter "
    "does not request or bypass it."
)


def _expand_roots() -> list[Path]:
    roots = [Path(root).expanduser() for root in APPLICATION_ROOTS]
    return _existing(*roots)


class MacOSHostFlavor(HostFlavor):
    """A macOS edition: a named ``.app`` bundle under an applications root."""

    def candidate_paths(self) -> list[Path]:
        return [root / self.bundle_name for root in _expand_roots()]

    def binary_path(self, bundle: Path) -> Path:
        """The Mach-O binary inside a bundle, named after the bundle stem."""
        return bundle / "Contents" / "MacOS" / self.bundle_name[: -len(".app")]

    def install_command(self) -> str | None:
        """A reviewable Homebrew cask command, or None when no cask exists."""
        if not self.package_id:
            return None
        return f"{HOMEBREW_CASK_COMMAND} {self.package_id}"


MACOS_FLAVORS: tuple[MacOSHostFlavor, ...] = (
    MacOSHostFlavor(
        name="capcut",
        package_id="capcut",
        process_names=("CapCut",),
        bundle_name="CapCut.app",
        homepage="https://www.capcut.com/",
    ),
    MacOSHostFlavor(
        name="jianyingpro",
        # Homebrew publishes no cask for 剪映专业版; only the official
        # download page is a reviewable install route.
        package_id="",
        process_names=("JianyingPro", "剪映专业版"),
        bundle_name="JianyingPro.app",
        homepage="https://www.jianying.com/",
    ),
)

DEFAULT_FLAVOR = MACOS_FLAVORS[0]


def _read_bundle_metadata(bundle: Path) -> dict[str, Any]:
    """Read version evidence from ``Contents/Info.plist``.

    The plist may be XML or binary; ``plistlib`` reads both. A bundle without a
    readable plist is still an installed application, so every failure here
    degrades to "version unknown" rather than an error.
    """
    plist = bundle / "Contents" / "Info.plist"
    try:
        with plist.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, ValueError, ExpatError, plistlib.InvalidFileException):
        # ExpatError is not a ValueError: an XML plist parses through expat, so
        # a truncated one would otherwise escape the "version unknown" fallback.
        return {}
    if not isinstance(info, dict):
        return {}
    return {
        "bundle_identifier": info.get("CFBundleIdentifier"),
        "bundle_version": info.get("CFBundleShortVersionString"),
        "bundle_build": info.get("CFBundleVersion"),
    }


class MacOSHostProvider(HostProvider):
    """macOS: bundle discovery, reviewable Homebrew/official-page plan."""

    name = "macos"
    platform = "posix"
    label = "macOS"
    supported = True
    #: ``dcc-cua`` is Windows-first. A missing CLI on macOS is a degraded
    #: diagnostic, not a failed prerequisite the operator must fix right now.
    window_inventory = "degraded"

    @property
    def flavors(self) -> tuple[MacOSHostFlavor, ...]:
        return MACOS_FLAVORS

    def _candidate_paths(self) -> list[Path]:
        candidates: list[Path] = []
        for flavor in MACOS_FLAVORS:
            candidates.extend(flavor.candidate_paths())
        return candidates

    def _discover(self) -> tuple[MacOSHostFlavor | None, Path | None, dict[str, Any]]:
        for flavor in MACOS_FLAVORS:
            for bundle in flavor.candidate_paths():
                if not bundle.is_dir():
                    continue
                metadata = _read_bundle_metadata(bundle)
                return flavor, bundle, metadata
        return None, None, {}

    def detect_installation(self) -> dict[str, Any]:
        candidates = self._candidate_paths()
        flavor, bundle, metadata = self._discover()
        resolved = flavor or DEFAULT_FLAVOR
        executable = flavor.binary_path(bundle) if flavor and bundle else None
        return {
            "installed": bundle is not None,
            # The bundle is the installable unit; ``executable`` is the Mach-O
            # inside it, reported when the bundle layout is intact.
            "executable": str(executable) if executable and executable.is_file() else None,
            "app_bundle": str(bundle) if bundle else None,
            "bundle_identifier": metadata.get("bundle_identifier"),
            "bundle_version": metadata.get("bundle_version"),
            "bundle_build": metadata.get("bundle_build"),
            "flavor": resolved.name,
            "candidates_checked": [str(path) for path in candidates],
            "package_id": resolved.package_id,
            "platform": os.name,
            "provider": self.name,
            "supported": True,
        }

    def installation_plan(self) -> dict[str, Any]:
        detection = self.detect_installation()
        flavor = next(
            (item for item in MACOS_FLAVORS if item.name == detection["flavor"]), DEFAULT_FLAVOR
        )
        command = flavor.install_command()
        return {
            "status": "installed" if detection["installed"] else "missing",
            "detection": detection,
            "installer": {
                "provider": "homebrew-cask" if command else "official-download",
                "package_id": flavor.package_id or None,
                "command": command,
                "download_pages": [item.homepage for item in MACOS_FLAVORS if item.homepage],
                "requires_operator_confirmation": True,
                "scope": "current_user_or_operator_selected",
                "notes": [
                    "No cask exists for 剪映专业版; install it from the official page."
                    if not command
                    else "Homebrew casks are community-maintained; review the token before use.",
                    ACCESSIBILITY_NOTE,
                ],
            },
            "environment": {
                "DCC_MCP_CAPCUT_BRIDGE_PORT": os.environ.get("DCC_MCP_CAPCUT_BRIDGE_PORT", "47410"),
                "DCC_MCP_CAPCUT_BRIDGE_TOKEN": "<generate-per-user-secret>",
                "DCC_MCP_CAPCUT_WINDOW_TITLE": "CapCut",
                "DCC_MCP_CAPCUT_INSTANCE_TYPE": "gui",
            },
            "post_install": [
                "Launch the editor once and complete any first-run prompts manually.",
                "Install/load the bundled dcc-mcp-capcut panel.",
                "Grant Accessibility to the controlling app so window binding can see the host.",
                "Verify bridge /health and the exact host PID through dcc-cua.",
                "Run inspect_project before any mutation.",
            ],
            "next_step": (
                "Call ui_control__system_operation with the operator-owned grant, "
                "then verify_installation."
            ),
        }

    def check_executable(self) -> dict[str, Any]:
        detection = self.detect_installation()
        if detection["installed"]:
            version = detection.get("bundle_version")
            suffix = f" (bundle {version})" if version else ""
            return {
                "status": "ok",
                "summary": f"found {detection['app_bundle']}{suffix}",
                "detail": detection,
                "hint": None,
            }
        commands = [item.install_command() for item in MACOS_FLAVORS]
        offered = [command for command in commands if command]
        pages = [item.homepage for item in MACOS_FLAVORS if item.homepage]
        hint = (
            "Install CapCut or 剪映专业版 for macOS with the operator-confirmed plan: "
            + "; ".join(offered + pages)
            + f". {ACCESSIBILITY_NOTE}"
        )
        return {
            "status": "fail",
            "summary": "no CapCut or JianyingPro application bundle found",
            "detail": detection,
            "hint": hint,
        }

    def window_binding_hint(self, *, inventory_unavailable: bool) -> str:
        if inventory_unavailable:
            return (
                "dcc-cua is not on PATH yet; macOS support for the window inventory "
                f"CLI is still being validated. {ACCESSIBILITY_NOTE}"
            )
        return (
            "Leave exactly one visible CapCut or 剪映专业版 main window open and "
            f"restored. {ACCESSIBILITY_NOTE}"
        )


__all__ = [
    "ACCESSIBILITY_NOTE",
    "APPLICATION_ROOTS",
    "DEFAULT_FLAVOR",
    "HOMEBREW_CASK_COMMAND",
    "MACOS_FLAVORS",
    "MacOSHostFlavor",
    "MacOSHostProvider",
]
