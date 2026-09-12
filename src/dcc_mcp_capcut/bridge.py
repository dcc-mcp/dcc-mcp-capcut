"""Loopback bridge shared by the MCP server and a CapCut extension/panel.

CapCut Desktop does not expose a stable public Python API.  The adapter keeps
the host boundary explicit: typed skills enqueue an action, and a signed
CapCut-side panel drains it and posts a result.  No raw script execution is
exposed through MCP.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.request import Request, urlopen


class CapCutBridge:
    """Authenticated, localhost-only request broker for CapCut actions."""

    PANEL_LEASE_SECONDS = 35.0

    def __init__(self, prefix: str = "DCC_MCP_CAPCUT", default_port: int = 47410) -> None:
        self.prefix = prefix
        self.port = int(os.environ.get(f"{prefix}_BRIDGE_PORT", default_port))
        self.token = os.environ.get(f"{prefix}_BRIDGE_TOKEN", "dev-token")
        self._pending: queue.Queue[dict[str, Any]] = queue.Queue()
        self._waiting: dict[str, tuple[threading.Event, dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._panel_seen_at: float | None = None
        os.environ.setdefault(f"{prefix}_BRIDGE_URL", f"http://127.0.0.1:{self.port}")

    def start(self) -> None:
        if self._httpd is not None:
            return
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if not self._authorized():
                    return self._send(403, {"error": "forbidden"})
                if self.path == "/health":
                    return self._send(200, bridge.health())
                if self.path == "/next":
                    return self._send(200, bridge.next())
                return self._send(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                if not self._authorized():
                    return self._send(403, {"error": "forbidden"})
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length))
                except (ValueError, json.JSONDecodeError):
                    return self._send(400, {"error": "invalid JSON"})
                if self.path == "/call":
                    try:
                        return self._send(
                            200, bridge.submit(payload["action"], payload.get("params", {}))
                        )
                    except (KeyError, RuntimeError) as error:
                        return self._send(503, {"error": str(error)})
                if self.path == "/result":
                    bridge.resolve(
                        payload.get("id", ""), payload.get("result"), payload.get("error")
                    )
                    return self._send(200, {"ok": True})
                return self._send(404, {"error": "not found"})

            def log_message(self, *_: Any) -> None:
                return

            def _authorized(self) -> bool:
                return self.headers.get("X-DCC-MCP-Token") == bridge.token

            def _send(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            self._thread = None

    def submit(self, action: str, params: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
        if not action or not isinstance(params, dict):
            raise ValueError("action and object params are required")
        request_id = uuid.uuid4().hex
        event, result = threading.Event(), {}
        with self._lock:
            self._waiting[request_id] = (event, result)
        self._pending.put({"id": request_id, "action": action, "params": params})
        if not event.wait(timeout):
            with self._lock:
                self._waiting.pop(request_id, None)
            raise RuntimeError("CapCut bridge did not respond; open the bundled panel")
        if "error" in result:
            raise RuntimeError(str(result["error"]))
        return result.get("result", {})

    def next(self) -> dict[str, Any]:
        with self._lock:
            self._panel_seen_at = time.monotonic()
        try:
            return self._pending.get(timeout=25)
        except queue.Empty:
            return {"id": None}

    def health(self) -> dict[str, Any]:
        """Report broker health separately from the CapCut-side consumer lease."""
        with self._lock:
            panel_seen_at = self._panel_seen_at
        panel_connected = bool(
            panel_seen_at is not None
            and time.monotonic() - panel_seen_at <= self.PANEL_LEASE_SECONDS
        )
        return {
            "ok": True,
            "pending": self._pending.qsize(),
            "panel_connected": panel_connected,
        }

    def resolve(self, request_id: str, result: Any, error: Any) -> None:
        with self._lock:
            waiting = self._waiting.pop(request_id, None)
        if waiting is None:
            return
        event, payload = waiting
        if error:
            payload["error"] = error
        else:
            payload["result"] = result if isinstance(result, dict) else {"value": result}
        event.set()


def call_bridge(action: str, params: dict[str, Any]) -> dict[str, Any]:
    """Call the running CapCut bridge from a declarative skill script."""
    prefix = "DCC_MCP_CAPCUT"
    url = os.environ.get(f"{prefix}_BRIDGE_URL", "http://127.0.0.1:47410").rstrip("/") + "/call"
    token = os.environ.get(f"{prefix}_BRIDGE_TOKEN", "dev-token")
    request = Request(
        url,
        data=json.dumps({"action": action, "params": params}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-DCC-MCP-Token": token},
        method="POST",
    )
    with urlopen(request, timeout=35) as response:  # noqa: S310 - adapter-owned loopback URL
        payload = json.loads(response.read().decode("utf-8"))
    if "error" in payload:
        raise RuntimeError(payload["error"])
    return payload
