import json
import socket
import threading

import pytest

from dcc_mcp_capcut.qt_probe import inspect_qt_host


def test_unconfigured_probe_does_not_claim_capabilities(monkeypatch):
    monkeypatch.delenv("DCC_CAPCUT_PROBE_ENDPOINT", raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        inspect_qt_host()


@pytest.mark.parametrize(
    "kwargs", [{"operation": "invoke"}, {"max_nodes": True}, {"max_depth": 21}]
)
def test_invalid_requests_rejected_before_connect(kwargs):
    with pytest.raises(ValueError):
        inspect_qt_host(**kwargs)


@pytest.fixture
def endpoint(tmp_path, monkeypatch):
    path = tmp_path / "endpoint.json"
    value = {"protocol": 1, "port": 1, "pid": 123, "exe_sha256": "a" * 64}
    path.write_text(json.dumps(value))
    monkeypatch.setenv("DCC_CAPCUT_PROBE_ENDPOINT", str(path))
    monkeypatch.setenv("DCC_CAPCUT_PROBE_TOKEN", "b" * 64)
    monkeypatch.setenv("DCC_CAPCUT_PROBE_EXE_SHA256", "a" * 64)
    monkeypatch.setenv("DCC_MCP_CAPCUT_PID", "123")
    return path, value


def test_stale_endpoint_rejected(endpoint, monkeypatch):
    monkeypatch.setenv("DCC_MCP_CAPCUT_PID", "456")
    with pytest.raises(RuntimeError, match="does not match"):
        inspect_qt_host()


@pytest.mark.parametrize("wrong_identity", [False, True])
def test_loopback_wire_contract(endpoint, wrong_identity):
    path, value = endpoint
    requests = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(5)
        value["port"] = listener.getsockname()[1]
        path.write_text(json.dumps(value))

        def serve():
            with listener.accept()[0] as peer, peer.makefile("rb") as stream:
                requests.append(json.loads(stream.readline()))
                response = {
                    **value,
                    "ok": True,
                    "backend": "qt-probe",
                    "verification_scope": "qt_metadata",
                    "pid": 456 if wrong_identity else 123,
                }
                peer.sendall(json.dumps(response).encode() + b"\n")

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            if wrong_identity:
                with pytest.raises(RuntimeError, match="does not match"):
                    inspect_qt_host()
            else:
                assert inspect_qt_host()["ok"] is True
        finally:
            thread.join(timeout=6)
        assert requests[0]["operation"] == "host.describe"
        assert requests[0]["token"] == "b" * 64
