import importlib.util
from pathlib import Path

_PATH = Path(__file__).parents[1] / "src/dcc_mcp_capcut/skills/capcut-setup/scripts/auto_setup.py"
_SPEC = importlib.util.spec_from_file_location("auto_setup", _PATH)
assert _SPEC and _SPEC.loader
auto_setup = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(auto_setup)


def test_auto_setup_requires_operator_grant():
    result = auto_setup.main()
    assert result["success"] is False
    assert "grant_id" in result["message"]


def test_auto_setup_forwards_install_and_bind_request(monkeypatch):
    monkeypatch.setattr(auto_setup, "detect_installation", lambda: {"installed": False})
    captured = {}

    def fake_call(action, params):
        captured.update(action=action, params=params)
        return {"accepted": True, "phase": "installing"}

    monkeypatch.setattr(auto_setup, "call_bridge", fake_call)
    result = auto_setup.main(grant_id="operator-grant", scope="current_user")

    assert result["success"] is True
    assert captured["action"] == "auto_setup_capcut"
    assert captured["params"]["install_required"] is True
    assert captured["params"]["bind_runtime"] is True
    assert captured["params"]["grant_id"] == "operator-grant"
