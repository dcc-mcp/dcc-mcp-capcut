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


def test_detection_covers_both_host_flavours(monkeypatch, tmp_path):
    """CapCut (international) and 剪映专业版/JianyingPro (China) are both discoverable."""
    from dcc_mcp_capcut.installer import HOST_FLAVORS, detect_installation

    assert [flavor.name for flavor in HOST_FLAVORS] == ["capcut", "jianyingpro"]

    jianying_dir = tmp_path / "JianyingPro" / "Apps"
    jianying_dir.mkdir(parents=True)
    (jianying_dir / "JianyingPro.exe").write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "none"))
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "none2"))

    found = detect_installation()
    assert found["installed"] is True
    assert found["flavor"] == "jianyingpro"
    assert found["package_id"] == "ByteDance.JianyingPro"
    assert found["executable"].endswith("JianyingPro.exe")


def test_capcut_wins_when_both_flavours_are_installed(monkeypatch, tmp_path):
    """Detection stays deterministic: the international build is reported first."""
    from dcc_mcp_capcut.installer import detect_installation

    for app_dir, exe in (("CapCut", "CapCut.exe"), ("JianyingPro", "JianyingPro.exe")):
        target = tmp_path / app_dir / "Apps"
        target.mkdir(parents=True)
        (target / exe).write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "none"))
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "none2"))

    found = detect_installation()
    assert found["flavor"] == "capcut"
    assert found["package_id"] == "ByteDance.CapCut"


def test_each_flavour_exposes_an_install_command():
    from dcc_mcp_capcut.installer import HOST_FLAVORS

    for flavor in HOST_FLAVORS:
        command = flavor.winget_command()
        assert command.startswith("winget install --id ")
        assert flavor.package_id in command
