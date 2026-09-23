import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dcc_mcp_capcut.bridge import CapCutBridge, call_bridge


def test_bridge_delivers_and_resolves_action():
    bridge = CapCutBridge("TEST_CAPCUT", 0)
    result = {}
    worker = threading.Thread(
        target=lambda: result.setdefault("value", bridge.submit("inspect_project", {}))
    )
    worker.start()
    job = bridge.next()
    assert job["action"] == "inspect_project"
    bridge.resolve(job["id"], {"project_name": "demo"}, None)
    worker.join(timeout=1)
    assert result["value"] == {"project_name": "demo"}


def test_bridge_reports_panel_connected_only_after_poll():
    bridge = CapCutBridge("TEST_CAPCUT_HEALTH", 0)
    assert bridge.health()["panel_connected"] is False

    worker = threading.Thread(target=lambda: bridge.submit("inspect_project", {}))
    worker.start()
    job = bridge.next()

    assert bridge.health()["panel_connected"] is True
    bridge.resolve(job["id"], {}, None)
    worker.join(timeout=1)


def test_bridge_rejects_error_result():
    bridge = CapCutBridge("TEST_CAPCUT_ERR", 0)
    result = {}
    worker = threading.Thread(target=lambda: result.setdefault("error", _submit(bridge)))
    worker.start()
    job = bridge.next()
    bridge.resolve(job["id"], None, "unsupported host")
    worker.join(timeout=1)
    assert result["error"] == "unsupported host"


def _submit(bridge):
    try:
        bridge.submit("export_video", {"output_path": "x.mp4"})
    except RuntimeError as exc:
        return str(exc)
    return "no error"


class _ErroringBridge:
    """A loopback broker that always answers with one status and body."""

    def __init__(self, status: int, body: bytes):
        self._status = status
        self._body = body
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def _handler(self):
        status, body = self._status, self._body

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return

        return Handler

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=2)


def test_call_bridge_propagates_the_error_body(monkeypatch):
    # The broker answers 503 with the panel-timeout text the skills document.
    # Before the fix urlopen raised HTTPError first and this body was dropped.
    server = _ErroringBridge(
        503, json.dumps({"error": "CapCut bridge did not respond; open the bundled panel"}).encode()
    )
    try:
        monkeypatch.setenv("DCC_MCP_CAPCUT_BRIDGE_URL", server.url)
        with pytest.raises(
            RuntimeError, match="CapCut bridge did not respond; open the bundled panel"
        ):
            call_bridge("inspect_project", {})
    finally:
        server.stop()


def test_call_bridge_names_the_status_when_the_body_is_not_error_json(monkeypatch):
    server = _ErroringBridge(403, b"forbidden")
    try:
        monkeypatch.setenv("DCC_MCP_CAPCUT_BRIDGE_URL", server.url)
        with pytest.raises(RuntimeError, match=r"HTTP 403: forbidden"):
            call_bridge("inspect_project", {})
    finally:
        server.stop()
