"""Safe CapCut installation discovery and operator-confirmed setup planning.

The adapter never shells out to an installer or edits the registry.  It emits
an exact, reviewable plan that an operator can approve through the core
``ui_control__system_operation`` grant, then verifies the resulting executable
and bridge configuration.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PACKAGE_ID = "ByteDance.CapCut"
WINGET_COMMAND = (
    "winget install --id ByteDance.CapCut --exact "
    "--accept-package-agreements --accept-source-agreements"
)


def _candidate_paths() -> list[Path]:
    roots = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "Apps",
        Path(os.environ.get("PROGRAMFILES", "")) / "CapCut",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "CapCut",
    ]
    return [root / "CapCut.exe" for root in roots if str(root) not in {".", ""}]


def detect_installation() -> dict[str, Any]:
    """Return deterministic, read-only installation evidence."""
    candidates = _candidate_paths()
    existing = [path for path in candidates if path.is_file()]
    return {
        "installed": bool(existing),
        "executable": str(existing[0]) if existing else None,
        "candidates_checked": [str(path) for path in candidates],
        "package_id": PACKAGE_ID,
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
