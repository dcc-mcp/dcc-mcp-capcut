import json

from dcc_mcp_capcut.installer import installation_plan, verify_installation


def test_installation_plan_is_reviewable_and_does_not_execute():
    plan = installation_plan()
    assert plan["installer"]["provider"] == "winget"
    assert plan["installer"]["package_id"] == "ByteDance.CapCut"
    assert plan["installer"]["requires_operator_confirmation"] is True
    assert "ui_control__system_operation" in plan["next_step"]


def test_verify_reports_not_ready_without_install_and_secret(monkeypatch):
    monkeypatch.delenv("DCC_MCP_CAPCUT_BRIDGE_TOKEN", raising=False)
    result = verify_installation()
    assert result["bridge_token_configured"] is False
    assert result["ready"] is False


def test_verify_rejects_bridge_without_connected_panel(monkeypatch):
    monkeypatch.setenv("DCC_MCP_CAPCUT_BRIDGE_TOKEN", "secret")
    monkeypatch.setenv("DCC_MCP_CAPCUT_BRIDGE_URL", "http://127.0.0.1:47410")
    monkeypatch.setenv("DCC_MCP_CAPCUT_PID", "31776")
    monkeypatch.setenv("DCC_MCP_CAPCUT_WINDOW_HANDLE", "106895862")
    monkeypatch.setattr(
        "dcc_mcp_capcut.installer.detect_installation",
        lambda: {"installed": True, "executable": "CapCut.exe"},
    )
    monkeypatch.setattr(
        "dcc_mcp_capcut.installer.urlopen",
        lambda *_args, **_kwargs: _Response({"ok": True, "panel_connected": False}),
    )

    result = verify_installation()

    assert result["bridge_reachable"] is True
    assert result["panel_connected"] is False
    assert result["exact_window_bound"] is True
    assert result["ready"] is False


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self._payload).encode("utf-8")
