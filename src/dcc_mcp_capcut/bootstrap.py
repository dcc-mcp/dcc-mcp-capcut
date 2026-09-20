"""Discover one visible CapCut window and run its bound MCP service."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Sequence

from .installer import HOST_FLAVORS
from .server import start_server, stop_server


class CapCutBindingError(RuntimeError):
    """CapCut could not be bound to one unambiguous visible main window."""


@dataclass(frozen=True)
class CapCutWindowBinding:
    pid: int
    window_handle: int
    title: str = "CapCut"


def flavor_by_exe(app_name: str):
    """Return the host flavour owning this executable name, or None."""
    normalized = str(app_name).casefold()
    return next((flavor for flavor in HOST_FLAVORS if flavor.exe.casefold() == normalized), None)


def _title_matches(window: dict[str, Any], flavor, *, bound: bool) -> bool:
    if bound:
        return True
    if flavor.window_title is None:
        # The flavour has no pinned main-window title; the executable name is
        # the discriminator, so every visible top-level window of that process
        # is eligible.
        return True
    return str(window.get("title", "")).casefold() == flavor.window_title.casefold()


def select_capcut_window(
    windows: list[dict[str, Any]], *, pid: int | None = None, window_handle: int | None = None
) -> CapCutWindowBinding:
    """Select exactly one visible, non-minimized CapCut main window."""
    if (pid is None) != (window_handle is None):
        raise CapCutBindingError("pid and window_handle must be supplied together")
    if pid is not None and (pid <= 0 or window_handle is None or window_handle <= 0):
        raise CapCutBindingError("pid and window_handle must be positive")
    candidates = [
        window
        for window in windows
        if (flavor := flavor_by_exe(window.get("app_name", ""))) is not None
        and _title_matches(window, flavor, bound=pid is not None)
        and (
            True
            if pid is None
            else window.get("pid") == pid and window.get("window_id") == window_handle
        )
        and window.get("is_on_screen") is True
        and window.get("minimized") is False
        and int(window.get("pid", 0)) > 0
        and int(window.get("window_id", 0)) > 0
        and int(window.get("bounds", {}).get("width", 0)) > 0
        and int(window.get("bounds", {}).get("height", 0)) > 0
    ]
    if not candidates:
        raise CapCutBindingError("no visible CapCut main window was found")
    if len(candidates) != 1:
        raise CapCutBindingError("multiple visible CapCut main windows were found")
    selected = candidates[0]
    return CapCutWindowBinding(
        pid=int(selected["pid"]),
        window_handle=int(selected["window_id"]),
        title=str(selected["title"]),
    )


def discover_capcut_window(
    *, pid: int | None = None, window_handle: int | None = None
) -> CapCutWindowBinding:
    """Read the official dcc-cua inventory without performing UI input."""
    try:
        completed = subprocess.run(
            ["dcc-cua", "list"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise CapCutBindingError("dcc-cua window inventory is unavailable") from exc
    try:
        windows = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CapCutBindingError("dcc-cua returned invalid window inventory JSON") from exc
    if not isinstance(windows, list):
        raise CapCutBindingError("dcc-cua window inventory must be a list")
    return select_capcut_window(windows, pid=pid, window_handle=window_handle)


def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--window-handle", type=int)
    parser.add_argument("--port", type=int)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if (args.pid is None) != (args.window_handle is None):
        parser.error("--pid and --window-handle must be supplied together")
    binding = discover_capcut_window(pid=args.pid, window_handle=args.window_handle)
    os.environ.setdefault("DCC_MCP_CAPCUT_BRIDGE_TOKEN", secrets.token_urlsafe(32))
    stopped = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    start_server(
        port=args.port,
        dcc_pid=binding.pid,
        dcc_window_handle=binding.window_handle,
        dcc_window_title=binding.title,
    )
    try:
        while not stopped.wait(1.0):
            if not process_is_alive(binding.pid):
                break
    finally:
        stop_server()


if __name__ == "__main__":  # pragma: no cover
    main()
