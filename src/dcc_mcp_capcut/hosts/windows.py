"""Windows host binding: the original, behaviour-preserving provider.

CapCut and 剪映专业版 both ship the same two-level launcher layout on Windows:
a per-user ``<app_dir>\\Apps\\<exe>`` install used by current releases, and an
older machine-wide ``<app_dir>\\<exe>`` install. Discovery and install planning
are unchanged from the pre-provider implementation; only their packaging moved.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .base import HostProvider
from .flavors import HostFlavor

PACKAGE_ID = "ByteDance.CapCut"
WINGET_COMMAND = (
    "winget install --id ByteDance.CapCut --exact "
    "--accept-package-agreements --accept-source-agreements"
)


class WindowsHostFlavor(HostFlavor):
    """A Windows edition: an ``.exe`` under one of the standard install roots."""

    def candidate_paths(self) -> list[Path]:
        # Filter the raw environment roots before appending the install layout.
        # An unset variable would otherwise produce a relative candidate such as
        # "CapCut/Apps/CapCut.exe", which can match a directory in the current
        # working directory instead of a real install root. Order is kept
        # identical to the original table: per-user Apps first.
        layouts = (
            (os.environ.get("LOCALAPPDATA", ""), Path(self.app_dir) / "Apps"),
            (os.environ.get("PROGRAMFILES", ""), Path(self.app_dir)),
            (os.environ.get("PROGRAMFILES(X86)", ""), Path(self.app_dir)),
        )
        return [
            root / layout / self.exe
            for root, layout in ((Path(value), layout) for value, layout in layouts)
            if str(root) not in {".", ""}
        ]

    def install_command(self) -> str:
        return (
            f"winget install --id {self.package_id} --exact "
            "--accept-package-agreements --accept-source-agreements"
        )

    # The pre-provider public name; kept so callers do not have to know that
    # the Windows installer happens to be winget.
    winget_command = install_command


WINDOWS_FLAVORS: tuple[WindowsHostFlavor, ...] = (
    WindowsHostFlavor(
        name="capcut",
        app_dir="CapCut",
        exe="CapCut.exe",
        package_id=PACKAGE_ID,
        process_names=("CapCut.exe",),
        window_title="CapCut",
    ),
    WindowsHostFlavor(
        name="jianyingpro",
        app_dir="JianyingPro",
        exe="JianyingPro.exe",
        package_id="ByteDance.JianyingPro",
        process_names=("JianyingPro.exe",),
    ),
)

DEFAULT_FLAVOR = WINDOWS_FLAVORS[0]


class WindowsHostProvider(HostProvider):
    """Windows: full discovery, winget install planning, exact window binding."""

    name = "windows"
    platform = "nt"
    label = "Windows"
    supported = True
    window_inventory = "supported"

    @property
    def flavors(self) -> tuple[WindowsHostFlavor, ...]:
        return WINDOWS_FLAVORS

    def host_version(self) -> str | None:
        """Windows ships no version the install layout exposes without a PE reader.

        Discovery only resolves an ``.exe`` path. Reading the version resource
        would need a PE parser the adapter does not depend on, and guessing from
        the install directory name would invent a fact, so the version stays
        ``None`` and grades as ``undetermined`` -- an explicit warning with a
        hint, never a silent pass.
        """
        return None

    def _candidate_paths(self) -> list[Path]:
        candidates: list[Path] = []
        for flavor in WINDOWS_FLAVORS:
            candidates.extend(flavor.candidate_paths())
        return candidates

    def detect_installation(self) -> dict[str, Any]:
        candidates = self._candidate_paths()
        found: tuple[WindowsHostFlavor, Path] | None = None
        for flavor in WINDOWS_FLAVORS:
            hit = next((path for path in flavor.candidate_paths() if path.is_file()), None)
            if hit is not None:
                found = (flavor, hit)
                break
        flavor, executable = found if found else (DEFAULT_FLAVOR, None)
        return {
            "installed": executable is not None,
            "executable": str(executable) if executable else None,
            "flavor": flavor.name,
            "candidates_checked": [str(path) for path in candidates],
            "package_id": flavor.package_id,
            "platform": os.name,
            "provider": self.name,
            "supported": True,
            **self.version_evidence(flavor.name),
        }

    def installation_plan(self) -> dict[str, Any]:
        detection = self.detect_installation()
        return {
            "status": "installed" if detection["installed"] else "missing",
            "detection": detection,
            "installer": {
                "provider": "winget",
                "package_id": PACKAGE_ID,
                "command": WINGET_COMMAND,
                "requires_operator_confirmation": True,
                "scope": "current_user_or_operator_selected",
            },
            "environment": {
                "DCC_MCP_CAPCUT_BRIDGE_PORT": os.environ.get("DCC_MCP_CAPCUT_BRIDGE_PORT", "47410"),
                "DCC_MCP_CAPCUT_BRIDGE_TOKEN": "<generate-per-user-secret>",
                "DCC_MCP_CAPCUT_WINDOW_TITLE": "CapCut",
                "DCC_MCP_CAPCUT_INSTANCE_TYPE": "gui",
            },
            "post_install": [
                "Launch CapCut Desktop once and complete any first-run prompts manually.",
                "Install/load the bundled dcc-mcp-capcut panel.",
                "Verify bridge /health and exact CapCut PID/HWND through dcc-cua.",
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
            return {
                "status": "ok",
                "summary": f"found {detection['executable']}",
                "detail": detection,
                "hint": None,
            }
        return {
            "status": "fail",
            "summary": "no CapCut executable found",
            "detail": detection,
            "hint": (f"Install CapCut Desktop with the operator-confirmed plan: {WINGET_COMMAND}"),
        }

    def window_binding_hint(self, *, inventory_unavailable: bool) -> str:
        if inventory_unavailable:
            return (
                "Install dcc-cua (the project-owned window inventory CLI) and make it "
                "resolvable on PATH."
            )
        return (
            "Launch CapCut Desktop and leave its main window visible and restored (not minimized)."
        )


__all__ = [
    "DEFAULT_FLAVOR",
    "PACKAGE_ID",
    "WINGET_COMMAND",
    "WINDOWS_FLAVORS",
    "WindowsHostFlavor",
    "WindowsHostProvider",
]
