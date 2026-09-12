import threading

from dcc_mcp_capcut.bridge import CapCutBridge


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
