"""Safe CapCut installation discovery and operator-confirmed setup planning.

The adapter never shells out to an installer or edits the registry.  It emits
an exact, reviewable plan that an operator can approve through the core
``ui_control__system_operation`` grant, then verifies the resulting executable
and bridge configuration.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PACKAGE_ID = "ByteDance.CapCut"
WINGET_COMMAND = (
    "winget install --id ByteDance.CapCut --exact "
    "--accept-package-agreements --accept-source-agreements"
)


@dataclass(frozen=True)
class HostFlavor:
    """One shipped desktop edition of the ByteDance editor.

    ByteDance publishes two desktop builds of the same product line: CapCut for
    international channels and 剪映专业版 (JianyingPro) for the China channel.
    Both ship the same two-level launcher layout, so one root table covers
    both: a per-user ``<app_dir>\\Apps\\<exe>`` install used by current
    releases, and an older machine-wide ``<app_dir>\\<exe>`` install.
    """

    name: str
    app_dir: str
    exe: str
    package_id: str
    # Verified title of the main window, or None when the executable name alone
    # identifies the flavour. JianyingPro main-window titles are localised and
    # vary by release, so they are deliberately not pinned here.
    window_title: str | None = None

    def winget_command(self) -> str:
        return (
            f"winget install --id {self.package_id} --exact "
            "--accept-package-agreements --accept-source-agreements"
        )

    def candidate_paths(self) -> list[Path]:
        roots = [
            Path(os.environ.get("LOCALAPPDATA", "")) / self.app_dir / "Apps",
            Path(os.environ.get("PROGRAMFILES", "")) / self.app_dir,
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / self.app_dir,
        ]
        return [root / self.exe for root in roots if str(root) not in {".", ""}]


HOST_FLAVORS: tuple[HostFlavor, ...] = (
    HostFlavor(
        name="capcut",
        app_dir="CapCut",
        exe="CapCut.exe",
        package_id=PACKAGE_ID,
        window_title="CapCut",
    ),
    HostFlavor(
        name="jianyingpro",
        app_dir="JianyingPro",
        exe="JianyingPro.exe",
        package_id="ByteDance.JianyingPro",
    ),
)

DEFAULT_FLAVOR = HOST_FLAVORS[0]


def _candidate_paths() -> list[Path]:
    candidates: list[Path] = []
    for flavor in HOST_FLAVORS:
        candidates.extend(flavor.candidate_paths())
    return candidates


def detect_installation() -> dict[str, Any]:
    """Return deterministic, read-only installation evidence."""
    candidates = _candidate_paths()
    found: tuple[HostFlavor, Path] | None = None
    for flavor in HOST_FLAVORS:
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
    }


def installation_plan() -> dict[str, Any]:
    """Build an operator-facing install/configure/verify plan."""
    detection = detect_installation()
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
        "next_step": "Call ui_control__system_operation with the operator-owned grant, then verify_installation.",
    }


def verify_installation(*, timeout: float = 2.0) -> dict[str, Any]:
    """Verify the executable, exact host binding, broker, and panel lease."""
    evidence = detect_installation()
    bridge_url = os.environ.get("DCC_MCP_CAPCUT_BRIDGE_URL", "http://127.0.0.1:47410").rstrip("/")
    token = os.environ.get("DCC_MCP_CAPCUT_BRIDGE_TOKEN", "")
    pid = _positive_int(os.environ.get("DCC_MCP_CAPCUT_PID"))
    window_handle = _positive_int(os.environ.get("DCC_MCP_CAPCUT_WINDOW_HANDLE"))
    evidence.update(
        {
            "bridge_url": bridge_url,
            "bridge_token_configured": bool(token),
            "dcc_pid": pid,
            "dcc_window_handle": window_handle,
            "exact_window_bound": bool(pid and window_handle),
            "bridge_reachable": False,
            "panel_connected": False,
            "bridge_error": None,
        }
    )

    if token:
        request = Request(
            f"{bridge_url}/health",
            headers={"X-DCC-MCP-Token": token},
            method="GET",
        )
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - adapter-owned loopback URL
                health = json.loads(response.read().decode("utf-8"))
            evidence["bridge_reachable"] = bool(health.get("ok"))
            evidence["panel_connected"] = bool(health.get("panel_connected"))
            evidence["bridge_health"] = health
        except (
            HTTPError,
            URLError,
            OSError,
            TimeoutError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            evidence["bridge_error"] = f"{type(error).__name__}: {error}"

    evidence["ready"] = bool(
        evidence["installed"]
        and evidence["bridge_token_configured"]
        and evidence["exact_window_bound"]
        and evidence["bridge_reachable"]
        and evidence["panel_connected"]
    )
    return evidence


def _positive_int(value: str | None) -> int | None:
    try:
        parsed = int(value or "")
    except ValueError:
        return None
    return parsed if parsed > 0 else None
