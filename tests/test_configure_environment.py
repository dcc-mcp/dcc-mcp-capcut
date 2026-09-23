"""The consent gate on ``configure_environment`` must be enforced locally."""

import importlib.util
from pathlib import Path

import pytest

_PATH = (
    Path(__file__).parents[1]
    / "src/dcc_mcp_capcut/skills/capcut-setup/scripts/configure_environment.py"
)
_SPEC = importlib.util.spec_from_file_location("configure_environment", _PATH)
assert _SPEC and _SPEC.loader
configure_environment = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(configure_environment)

_COMMON = importlib.import_module("dcc_mcp_capcut.skills._shared.scripts.common")


@pytest.fixture
def no_dispatch(monkeypatch):
    """Fail loudly if the skill reaches the bridge at all."""

    def boom(action, params):  # pragma: no cover - only runs on a regression
        raise AssertionError(f"dispatched {action} without an operator grant")

    monkeypatch.setattr(_COMMON, "call_bridge", boom)
    return boom


def test_configure_environment_requires_operator_grant(no_dispatch):
    result = configure_environment.main(bridge_port=47410)

    assert result["success"] is False
    assert "grant_id" in result["message"]


def test_configure_environment_dispatches_with_a_grant(monkeypatch):
    captured = {}

    def fake_call(action, params):
        captured.update(action=action, params=params)
        # configure_environment mutates, so the host must return a verified readback.
        return {
            "bridge_url": "http://127.0.0.1:47410",
            "bridge_port": 47410,
            "verification": {"ok": True},
        }

    monkeypatch.setattr(_COMMON, "call_bridge", fake_call)

    result = configure_environment.main(bridge_port=47410, grant_id="operator-grant")

    assert result["success"] is True
    assert captured["action"] == "configure_environment"
    assert captured["params"]["grant_id"] == "operator-grant"
