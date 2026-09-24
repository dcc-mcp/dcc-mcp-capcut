"""Safe CapCut installation discovery and operator-confirmed setup planning.

The adapter never shells out to an installer or edits the registry.  It emits
an exact, reviewable plan that an operator can approve through the core
``ui_control__system_operation`` grant, then verifies the resulting executable
and bridge configuration.

Every platform assumption lives in :mod:`dcc_mcp_capcut.hosts`. This module is
the stable public surface: it resolves the provider for the running platform
and forwards, so a caller written against the Windows behaviour keeps working
while macOS gains real discovery and Linux gets an explicit ``unsupported``
verdict instead of a silently empty one.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .bridge import DEFAULT_BRIDGE_TOKEN
from .hosts import PACKAGE_ID, WINDOWS_FLAVORS, WINGET_COMMAND, HostFlavor, get_provider
from .hosts.windows import WindowsHostFlavor

# The Windows edition table (CapCut + 剪映专业版) is the canonical list of
# shipped desktop editions and their package ids. Platform-aware code must read
# `hosts.get_provider().flavors` instead: macOS editions are application bundles
# with different installation facts and no Windows executable name.
HOST_FLAVORS = WINDOWS_FLAVORS
DEFAULT_FLAVOR = WINDOWS_FLAVORS[0]

__all__ = [
    "DEFAULT_FLAVOR",
    "HOST_FLAVORS",
    "PACKAGE_ID",
    "WINGET_COMMAND",
    "HostFlavor",
    "WindowsHostFlavor",
    "detect_installation",
    "installation_plan",
    "verify_installation",
]


def detect_installation() -> dict[str, Any]:
    """Return deterministic, read-only installation evidence for this platform."""
    return get_provider().detect_installation()


def installation_plan() -> dict[str, Any]:
    """Build an operator-facing install/configure/verify plan for this platform."""
    return get_provider().installation_plan()


def verify_installation(*, timeout: float = 2.0) -> dict[str, Any]:
    """Verify the executable, exact host binding, broker, and panel lease."""
    evidence = dict(detect_installation())
    bridge_url = os.environ.get("DCC_MCP_CAPCUT_BRIDGE_URL", "http://127.0.0.1:47410").rstrip("/")
    configured_token = os.environ.get("DCC_MCP_CAPCUT_BRIDGE_TOKEN", "")
    # The health probe uses the same default as call_bridge. Without the
    # fallback an unset token skipped the probe entirely and reported
    # bridge_reachable=false with a null error, which reads as "bridge down"
    # when the bridge is in fact up on the documented default token.
    probe_token = configured_token or DEFAULT_BRIDGE_TOKEN
    pid = _positive_int(os.environ.get("DCC_MCP_CAPCUT_PID"))
    window_handle = _positive_int(os.environ.get("DCC_MCP_CAPCUT_WINDOW_HANDLE"))
    evidence.update(
        {
            "bridge_url": bridge_url,
            "bridge_token_configured": bool(configured_token),
            # The token actually in force, as opposed to the token the operator
            # set. It is True both when the token is unset and when it is
            # explicitly the default, because in both cases the bridge speaks
            # the shared default -- which is a security warning, not a
            # readiness failure. Doctor reports the narrower
            # ``uses_default_token``, which is False while unset.
            "token_is_default": probe_token == DEFAULT_BRIDGE_TOKEN,
            "dcc_pid": pid,
            "dcc_window_handle": window_handle,
            "exact_window_bound": bool(pid and window_handle),
            "bridge_reachable": False,
            "panel_connected": False,
            "bridge_error": None,
        }
    )

    try:
        # Built inside the try: Request() rejects an unusable URL (e.g. an
        # explicitly empty DCC_MCP_CAPCUT_BRIDGE_URL) before any socket is
        # opened, and that verdict belongs in bridge_error, not in a raised
        # exception -- callers use this as diagnostic evidence.
        request = Request(
            f"{bridge_url}/health",
            headers={"X-DCC-MCP-Token": probe_token},
            method="GET",
        )
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - adapter-owned loopback URL
            health = json.loads(response.read().decode("utf-8"))
        if not isinstance(health, dict):
            # The doctor probes this endpoint while the port is held by another
            # process, so a non-object reply is a real possibility, not a
            # hypothetical one.
            raise ValueError(f"unexpected /health payload: {type(health).__name__}")
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

    # The token is deliberately absent from this gate. ``ready`` answers "can
    # the adapter bind this host and reach the panel right now", and the bridge
    # answers that question on whatever token is configured -- including the
    # documented default. A weak token is a security warning the doctor grades
    # as `warn` (see ``check_bridge_token``); it is not a wiring fault, so it
    # must not be able to veto readiness on its own. Both token facts stay in
    # the evidence above, and ``token_is_default`` is the field to alert on.
    evidence["ready"] = bool(
        evidence["installed"]
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
