"""Preflight doctor: verdicts, exit-code contract, and read-only guarantees."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import types
from pathlib import Path

import pytest

from dcc_mcp_capcut import doctor
from dcc_mcp_capcut.__version__ import __version__

PYPROJECT = Path(__file__).parents[1] / "pyproject.toml"

VISIBLE_WINDOW = {
    "app_name": "CapCut.exe",
    "pid": 42,
    "window_id": 99,
    "title": "CapCut",
    "is_on_screen": True,
    "minimized": False,
    "bounds": {"width": 1920, "height": 1080},
}


def _window(pid: int, handle: int) -> dict:
    return {**VISIBLE_WINDOW, "pid": pid, "window_id": handle}


@pytest.fixture(autouse=True)
def _clean_probe_env(monkeypatch):
    """Keep every environment-driven check deterministic."""
    for name in (
        "DCC_CAPCUT_PROBE_ENDPOINT",
        "DCC_CAPCUT_PROBE_TOKEN",
        "DCC_CAPCUT_PROBE_EXE_SHA256",
        "DCC_MCP_CAPCUT_PID",
        "DCC_MCP_CAPCUT_BRIDGE_PORT",
        "DCC_MCP_CAPCUT_BRIDGE_TOKEN",
        "DCC_MCP_RUNTIME_ID",
        "DCC_MCP_RUNTIME_VERSION",
        "DCC_MCP_RUNTIME_CAPABILITIES_FINGERPRINT",
        "DCC_MCP_PYTHON_EXECUTABLE",
    ):
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------
# version helpers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "installed, minimum, expected",
    [
        ("0.19.13", "0.19.13", True),
        ("0.20.25", "0.19.13", True),
        ("0.19.12", "0.19.13", False),
        ("0.20", "0.19.13", True),
        ("0.20.25rc1", "0.20.25", True),
        ("1.0.0", "0.19.13", True),
        ("0.9.0", "0.19.13", False),
    ],
)
def test_version_floor_comparison(installed, minimum, expected):
    assert doctor._version_at_least(installed, minimum) is expected


def test_declared_floors_match_pyproject():
    text = PYPROJECT.read_text(encoding="utf-8")
    requires_python = re.search(r'^requires-python\s*=\s*">=(\d+)\.(\d+)"', text, re.M)
    core_floor = re.search(r'"dcc-mcp-core>=([\d.]+),<1\.0\.0"', text)
    assert requires_python and core_floor
    assert doctor.MIN_PYTHON == (int(requires_python[1]), int(requires_python[2]))
    assert doctor.MIN_CORE_VERSION == core_floor[1]


# --------------------------------------------------------------------------
# python
# --------------------------------------------------------------------------


def test_python_check_passes_on_a_supported_interpreter():
    check = doctor.check_python()
    assert check.status == doctor.OK
    assert check.detail["version"] == doctor._python_version()


def test_python_check_fails_below_the_supported_minimum(monkeypatch):
    monkeypatch.setattr(sys, "version_info", (3, 8, 20, "final", 0))
    check = doctor.check_python()
    assert check.status == doctor.FAIL
    assert "3.8" in check.summary
    assert check.hint


# --------------------------------------------------------------------------
# dcc_mcp_core
# --------------------------------------------------------------------------


def test_core_check_fails_when_not_importable(monkeypatch):
    monkeypatch.setitem(sys.modules, "dcc_mcp_core", None)
    check = doctor.check_core()
    assert check.status == doctor.FAIL
    assert "not importable" in check.summary
    assert "dcc-mcp-core>=" in check.hint


def test_core_check_fails_below_the_verified_floor(monkeypatch):
    monkeypatch.setattr(doctor, "_distribution_version", lambda _name: "0.19.0")
    check = doctor.check_core()
    assert check.status == doctor.FAIL
    assert doctor.MIN_CORE_VERSION in check.summary
    assert check.hint


def test_core_check_warns_without_version_metadata(monkeypatch):
    def _no_lazy_attribute(name):
        raise AttributeError(name)

    monkeypatch.setattr(doctor, "_distribution_version", lambda _name: None)
    monkeypatch.setattr(sys.modules["dcc_mcp_core"], "__getattr__", _no_lazy_attribute)
    check = doctor.check_core()
    assert check.status == doctor.WARN
    assert check.detail["installed"] is None
    assert check.hint


def test_core_check_passes_on_the_verified_floor(monkeypatch):
    monkeypatch.setattr(doctor, "_distribution_version", lambda _name: doctor.MIN_CORE_VERSION)
    check = doctor.check_core()
    assert check.status == doctor.OK


# --------------------------------------------------------------------------
# runtime handshake
# --------------------------------------------------------------------------


def _install_fake_runtime(monkeypatch, **overrides):
    handshake = types.SimpleNamespace(
        **{
            "adapter_id": "capcut",
            "adapter_version": __version__,
            "runtime_id": "runtime-1",
            "runtime_version": "1.2.3",
            "capabilities_fingerprint": "fingerprint",
            **overrides,
        }
    )
    calls = []

    def require_adapter(adapter_id):
        calls.append(adapter_id)
        return types.SimpleNamespace(handshake=handshake)

    bootstrap = types.ModuleType("dcc_mcp_runtime.bootstrap")
    bootstrap.require_adapter = require_adapter
    runtime = types.ModuleType("dcc_mcp_runtime")
    runtime.bootstrap = bootstrap
    monkeypatch.setitem(sys.modules, "dcc_mcp_runtime", runtime)
    monkeypatch.setitem(sys.modules, "dcc_mcp_runtime.bootstrap", bootstrap)
    return calls, handshake


def test_runtime_check_warns_when_the_bundle_is_absent(monkeypatch):
    monkeypatch.setitem(sys.modules, "dcc_mcp_runtime", None)
    check = doctor.check_runtime()
    assert check.status == doctor.WARN
    assert check.detail["error_code"] == "DCC_MCP_RUNTIME_MISSING"
    assert check.hint


def test_runtime_check_fails_on_a_stale_adapter_version(monkeypatch):
    _install_fake_runtime(monkeypatch, adapter_version="0.0.1")
    check = doctor.check_runtime()
    assert check.status == doctor.FAIL
    assert check.detail["error_code"] == "DCC_MCP_RUNTIME_ADAPTER_VERSION_MISMATCH"
    assert check.hint


def test_runtime_check_fails_on_a_missing_metadata_field(monkeypatch):
    _install_fake_runtime(monkeypatch, runtime_version=None)
    check = doctor.check_runtime()
    assert check.status == doctor.FAIL
    assert check.detail["error_code"] == "DCC_MCP_RUNTIME_HANDSHAKE_INVALID"


def test_runtime_check_fails_on_a_foreign_handshake(monkeypatch):
    _install_fake_runtime(monkeypatch, adapter_id="premiere")
    check = doctor.check_runtime()
    assert check.status == doctor.FAIL


def test_runtime_check_fails_when_the_probe_raises(monkeypatch):
    bootstrap = types.ModuleType("dcc_mcp_runtime.bootstrap")

    def require_adapter(_adapter_id):
        raise FileNotFoundError("no adapter manifest")

    bootstrap.require_adapter = require_adapter
    runtime = types.ModuleType("dcc_mcp_runtime")
    runtime.bootstrap = bootstrap
    monkeypatch.setitem(sys.modules, "dcc_mcp_runtime", runtime)
    monkeypatch.setitem(sys.modules, "dcc_mcp_runtime.bootstrap", bootstrap)
    check = doctor.check_runtime()
    assert check.status == doctor.FAIL
    assert "FileNotFoundError" in check.summary
    assert check.hint


def test_runtime_check_passes_and_reports_handshake_metadata(monkeypatch):
    _install_fake_runtime(monkeypatch)
    check = doctor.check_runtime()
    assert check.status == doctor.OK
    assert check.detail["handshake"] == {
        "adapter_id": "capcut",
        "adapter_version": __version__,
        "runtime_id": "runtime-1",
        "runtime_version": "1.2.3",
        "capabilities_fingerprint": "fingerprint",
    }


def test_runtime_probe_does_not_mutate_the_environment(monkeypatch):
    """The handshake probe writes env vars; the doctor must not leak them."""
    _install_fake_runtime(monkeypatch)
    before = dict(os.environ)
    doctor.check_runtime()
    assert dict(os.environ) == before


# --------------------------------------------------------------------------
# CapCut executable
# --------------------------------------------------------------------------


def test_executable_check_passes_when_installed(pin_platform, monkeypatch):
    provider = pin_platform("windows")
    monkeypatch.setattr(
        type(provider),
        "detect_installation",
        lambda _self: {"installed": True, "executable": "C:/CapCut/CapCut.exe"},
    )
    check = doctor.check_capcut_executable()
    assert check.status == doctor.OK
    assert "CapCut.exe" in check.summary


def test_executable_check_fails_on_windows_when_missing(pin_platform, monkeypatch):
    provider = pin_platform("windows")
    monkeypatch.setattr(type(provider), "detect_installation", lambda _self: {"installed": False})
    check = doctor.check_capcut_executable()
    assert check.status == doctor.FAIL
    assert "winget" in check.hint


def test_executable_check_reports_the_macos_bundle(pin_platform, monkeypatch):
    """macOS is a real diagnostic path, not a skipped one."""
    provider = pin_platform("macos")
    monkeypatch.setattr(
        type(provider),
        "detect_installation",
        lambda _self: {
            "installed": True,
            "app_bundle": "/Applications/JianyingPro.app",
            "bundle_version": "6.9.0",
        },
    )
    check = doctor.check_capcut_executable()
    assert check.status == doctor.OK
    assert "/Applications/JianyingPro.app" in check.summary
    assert "6.9.0" in check.summary


def test_executable_check_fails_on_macos_when_missing(pin_platform, monkeypatch):
    """A missing macOS host is a failed prerequisite, not a skip."""
    provider = pin_platform("macos")
    monkeypatch.setattr(type(provider), "detect_installation", lambda _self: {"installed": False})
    check = doctor.check_capcut_executable()
    assert check.status == doctor.FAIL
    assert "brew install --cask" in check.hint
    assert "Accessibility" in check.hint


def test_executable_check_reports_linux_as_unsupported(pin_platform):
    """Linux gets an explicit conclusion with a reason, never a silent skip."""
    pin_platform("linux")
    check = doctor.check_capcut_executable()
    assert check.status == doctor.SKIP
    assert "unsupported" in check.summary.lower()
    assert check.detail["unsupported"] is True
    assert check.detail["reason"]
    assert check.hint


# --------------------------------------------------------------------------
# dcc-cua availability and window uniqueness
# --------------------------------------------------------------------------


def test_cua_check_skips_on_linux(pin_platform):
    """No official client exists, so no window inventory is attempted."""
    pin_platform("linux")
    check = doctor.check_dcc_cua()
    assert check.status == doctor.SKIP
    assert "unsupported" in check.summary.lower()
    assert check.hint


def test_cua_check_warns_on_macos_without_the_cli(pin_platform, monkeypatch):
    """macOS window binding is real but still being validated, and it depends on
    a user-granted Accessibility permission, so a missing CLI degrades rather
    than fails."""
    pin_platform("macos")

    def missing(*_args, **_kwargs):
        raise FileNotFoundError("dcc-cua")

    monkeypatch.setattr(doctor, "_dcc_cua_inventory", missing)
    check = doctor.check_dcc_cua()
    assert check.status == doctor.WARN
    assert "Accessibility" in check.hint


def test_cua_check_binds_a_macos_bundle_window(pin_platform, monkeypatch):
    pin_platform("macos")
    monkeypatch.setattr(
        doctor,
        "_dcc_cua_inventory",
        lambda *_a, **_k: [
            {
                "app_name": "CapCut",
                "pid": 512,
                "window_id": 4096,
                "title": "CapCut",
                "is_on_screen": True,
                "minimized": False,
                "bounds": {"width": 1728, "height": 1117},
            }
        ],
    )
    check = doctor.check_dcc_cua()
    assert check.status == doctor.OK
    assert check.detail["pid"] == 512


def test_cua_check_fails_when_the_cli_is_missing(pin_platform, monkeypatch):
    pin_platform("windows")

    def missing(*_args, **_kwargs):
        raise FileNotFoundError("dcc-cua")

    monkeypatch.setattr(doctor, "_dcc_cua_inventory", missing)
    check = doctor.check_dcc_cua()
    assert check.status == doctor.FAIL
    assert "not on PATH" in check.summary
    assert check.hint


def test_cua_check_fails_when_the_cli_times_out(pin_platform, monkeypatch):
    pin_platform("windows")

    def stalled(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="dcc-cua list", timeout=15)

    monkeypatch.setattr(doctor, "_dcc_cua_inventory", stalled)
    check = doctor.check_dcc_cua()
    assert check.status == doctor.FAIL
    assert "timed out" in check.summary


def test_cua_check_fails_when_the_cli_exits_nonzero(pin_platform, monkeypatch):
    pin_platform("windows")

    def failed(*_args, **_kwargs):
        raise subprocess.CalledProcessError(returncode=3, cmd="dcc-cua list")

    monkeypatch.setattr(doctor, "_dcc_cua_inventory", failed)
    check = doctor.check_dcc_cua()
    assert check.status == doctor.FAIL
    assert "exited with 3" in check.summary


def test_cua_check_fails_on_invalid_inventory(pin_platform, monkeypatch):
    pin_platform("windows")

    def invalid(*_args, **_kwargs):
        raise json.JSONDecodeError("no json", doc="", pos=0)

    monkeypatch.setattr(doctor, "_dcc_cua_inventory", invalid)
    check = doctor.check_dcc_cua()
    assert check.status == doctor.FAIL
    assert "invalid" in check.summary


def test_cua_check_fails_when_no_window_is_open(pin_platform, monkeypatch):
    pin_platform("windows")
    monkeypatch.setattr(
        doctor, "_dcc_cua_inventory", lambda *_a, **_k: [{"app_name": "notepad.exe"}]
    )
    check = doctor.check_dcc_cua()
    assert check.status == doctor.FAIL
    assert "no visible CapCut main window" in check.summary
    assert "Launch CapCut" in check.hint


def test_cua_check_fails_on_ambiguous_windows(pin_platform, monkeypatch):
    pin_platform("windows")
    monkeypatch.setattr(
        doctor, "_dcc_cua_inventory", lambda *_a, **_k: [_window(1, 2), _window(3, 4)]
    )
    check = doctor.check_dcc_cua()
    assert check.status == doctor.FAIL
    assert "multiple" in check.summary
    assert "exactly one" in check.hint


def test_cua_check_passes_on_one_visible_window(pin_platform, monkeypatch):
    pin_platform("windows")
    monkeypatch.setattr(doctor, "_dcc_cua_inventory", lambda *_a, **_k: [_window(42, 99)])
    check = doctor.check_dcc_cua()
    assert check.status == doctor.OK
    assert check.detail["pid"] == 42


# --------------------------------------------------------------------------
# bridge port and token
# --------------------------------------------------------------------------


def test_port_check_passes_when_the_port_is_free(monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()
    monkeypatch.setenv("DCC_MCP_CAPCUT_BRIDGE_PORT", str(port))
    check = doctor.check_bridge_port()
    assert check.status == doctor.OK
    assert check.detail["port"] == port


def test_port_check_fails_when_the_port_is_taken(monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        monkeypatch.setenv("DCC_MCP_CAPCUT_BRIDGE_PORT", str(listener.getsockname()[1]))
        monkeypatch.setattr(doctor, "verify_installation", lambda: {"bridge_reachable": True})
        check = doctor.check_bridge_port()
    assert check.status == doctor.FAIL
    assert "already in use" in check.summary
    assert check.detail["running_bridge"] == {"bridge_reachable": True}
    assert check.hint


def test_port_check_falls_back_to_the_default_port(monkeypatch):
    monkeypatch.setenv("DCC_MCP_CAPCUT_BRIDGE_PORT", "not-a-port")
    monkeypatch.setattr(doctor, "_port_is_free", lambda port: port == doctor.DEFAULT_BRIDGE_PORT)
    assert doctor.check_bridge_port().detail["port"] == doctor.DEFAULT_BRIDGE_PORT


def test_token_check_warns_when_unset():
    check = doctor.check_bridge_token()
    assert check.status == doctor.WARN
    assert check.detail["configured"] is False
    assert check.hint


def test_token_check_warns_on_the_shared_default(monkeypatch):
    monkeypatch.setenv("DCC_MCP_CAPCUT_BRIDGE_TOKEN", doctor.DEFAULT_BRIDGE_TOKEN)
    check = doctor.check_bridge_token()
    assert check.status == doctor.WARN
    assert check.detail["uses_default_token"] is True
    assert check.hint


def test_token_check_passes_on_a_per_user_secret(monkeypatch):
    monkeypatch.setenv("DCC_MCP_CAPCUT_BRIDGE_TOKEN", "s" * 43)
    check = doctor.check_bridge_token()
    assert check.status == doctor.OK
    assert check.detail["uses_default_token"] is False
    assert "s" * 43 not in check.summary


# --------------------------------------------------------------------------
# panel payload
# --------------------------------------------------------------------------


def test_panel_check_passes_for_the_shipped_payload():
    check = doctor.check_panel_files()
    assert check.status == doctor.OK
    assert check.detail["missing"] == []


def test_panel_check_fails_when_the_payload_is_incomplete(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(doctor, "PANEL_DIR", tmp_path)
    check = doctor.check_panel_files()
    assert check.status == doctor.FAIL
    assert check.detail["missing"] == ["HOST_API.md", "panel.js"]
    assert check.hint


# --------------------------------------------------------------------------
# Qt probe
# --------------------------------------------------------------------------


def test_qt_probe_check_warns_when_unconfigured():
    check = doctor.check_qt_probe()
    assert check.status == doctor.WARN
    assert check.detail["missing"] == list(sorted(doctor.QT_PROBE_ENV))
    assert check.hint


def test_qt_probe_check_warns_on_a_malformed_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("DCC_CAPCUT_PROBE_ENDPOINT", str(tmp_path / "endpoint.json"))
    monkeypatch.setenv("DCC_CAPCUT_PROBE_TOKEN", "short")
    monkeypatch.setenv("DCC_CAPCUT_PROBE_EXE_SHA256", "nope")
    check = doctor.check_qt_probe()
    assert check.status == doctor.WARN
    assert "32 bytes" in " ".join(check.detail["problems"])
    assert "64 lowercase hex" in " ".join(check.detail["problems"])
    assert check.hint


def test_qt_probe_check_passes_when_fully_configured(monkeypatch, tmp_path):
    endpoint = tmp_path / "endpoint.json"
    endpoint.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DCC_CAPCUT_PROBE_ENDPOINT", str(endpoint))
    monkeypatch.setenv("DCC_CAPCUT_PROBE_TOKEN", "b" * 64)
    monkeypatch.setenv("DCC_CAPCUT_PROBE_EXE_SHA256", "a" * 64)
    monkeypatch.setenv("DCC_MCP_CAPCUT_PID", "4242")
    check = doctor.check_qt_probe()
    assert check.status == doctor.OK
    assert check.detail["problems"] == []


# --------------------------------------------------------------------------
# optional interchange extra
# --------------------------------------------------------------------------


def test_otio_check_warns_when_the_extra_is_absent(monkeypatch):
    monkeypatch.setitem(sys.modules, "opentimelineio", None)
    check = doctor.check_opentimelineio()
    assert check.status == doctor.WARN
    assert "interchange" in check.hint


def test_otio_check_passes_when_importable(monkeypatch):
    module = types.ModuleType("opentimelineio")
    module.__version__ = "0.17.0"
    monkeypatch.setitem(sys.modules, "opentimelineio", module)
    check = doctor.check_opentimelineio()
    assert check.status == doctor.OK
    assert check.detail["installed"] == "0.17.0"


# --------------------------------------------------------------------------
# report, exit codes, and CLI surface
# --------------------------------------------------------------------------


def test_run_checks_covers_every_registered_check(pin_platform):
    pin_platform("linux")
    checks = doctor.run_checks()
    assert [check.name for check in checks] == [name for name, _ in doctor.CHECKS]


def test_a_broken_check_becomes_a_failed_check(monkeypatch):
    def boom():
        raise RuntimeError("diagnostic exploded")

    monkeypatch.setattr(doctor, "CHECKS", (("python", boom),))
    (check,) = doctor.run_checks()
    assert check.status == doctor.FAIL
    assert "diagnostic exploded" in check.summary
    assert check.hint


@pytest.mark.parametrize(
    "statuses, expected",
    [
        ((doctor.OK, doctor.OK), doctor.EXIT_OK),
        ((doctor.OK, doctor.SKIP), doctor.EXIT_OK),
        ((doctor.OK, doctor.WARN), doctor.EXIT_OK),
        ((doctor.OK, doctor.FAIL), doctor.EXIT_FAILED),
        ((doctor.WARN, doctor.SKIP, doctor.FAIL), doctor.EXIT_FAILED),
    ],
)
def test_exit_code_contract(statuses, expected):
    checks = tuple(
        doctor.Check(name=f"check{index}", status=status, summary=status)
        for index, status in enumerate(statuses)
    )
    report = doctor.Report(checks=checks)
    assert report.exit_code == expected
    assert report.ok is (expected == doctor.EXIT_OK)
    assert len(report.failures) == statuses.count(doctor.FAIL)


def test_json_report_is_machine_readable(monkeypatch, capsys):
    monkeypatch.setattr(
        doctor,
        "CHECKS",
        (
            ("python", lambda: doctor.Check("python", doctor.OK, "fine")),
            (
                "bridge_token",
                lambda: doctor.Check("bridge_token", doctor.FAIL, "bad", hint="fix it"),
            ),
        ),
    )
    assert doctor.main(["--json"]) == doctor.EXIT_FAILED
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert report["exit_code"] == doctor.EXIT_FAILED
    assert report["version"] == __version__
    assert report["platform"] == os.name
    assert report["counts"] == {
        doctor.OK: 1,
        doctor.WARN: 0,
        doctor.FAIL: 1,
        doctor.SKIP: 0,
    }
    assert [check["name"] for check in report["checks"]] == ["python", "bridge_token"]
    assert report["checks"][1]["hint"] == "fix it"


def test_human_report_hides_hints_until_asked(monkeypatch, capsys):
    monkeypatch.setattr(
        doctor,
        "CHECKS",
        (
            (
                "bridge_token",
                lambda: doctor.Check("bridge_token", doctor.WARN, "weak", hint="rotate it"),
            ),
        ),
    )
    assert doctor.main([]) == doctor.EXIT_OK
    plain = capsys.readouterr().out
    assert "[warn]" in plain
    assert "rotate it" not in plain
    assert "--fix-hints" in plain

    assert doctor.main(["--fix-hints"]) == doctor.EXIT_OK
    with_hints = capsys.readouterr().out
    assert "fix: rotate it" in with_hints
    assert "1 warned" in with_hints


def test_cli_rejects_unknown_flags():
    with pytest.raises(SystemExit) as raised:
        doctor.main(["--mutate"])
    assert raised.value.code == 2


def test_doctor_never_mutates_the_environment(pin_platform):
    pin_platform("linux")
    before = dict(os.environ)
    doctor.run_doctor()
    assert dict(os.environ) == before


# ---------------------------------------------------------------------------
# The external ASR executor seam
# ---------------------------------------------------------------------------


@pytest.fixture
def asr_env(monkeypatch):
    """Control the ASR seam without touching the real environment."""

    def _set(value):
        if value is None:
            monkeypatch.delenv("DCC_MCP_CAPCUT_ASR_EXECUTOR", raising=False)
        else:
            monkeypatch.setenv("DCC_MCP_CAPCUT_ASR_EXECUTOR", str(value))
        return doctor.check_asr_executor()

    return _set


def test_an_unset_executor_is_a_warning_and_names_the_variable(asr_env):
    """Acceptance: the doctor must say plainly that no ASR executor is configured."""
    check = asr_env(None)

    assert check.name == "asr_executor"
    assert check.status == doctor.WARN
    assert "no ASR executor configured" in check.summary
    assert "DCC_MCP_CAPCUT_ASR_EXECUTOR" in check.summary
    assert check.detail == {
        "configured": False,
        "env": "DCC_MCP_CAPCUT_ASR_EXECUTOR",
        "usable": False,
    }


def test_the_unset_warning_says_the_adapter_ships_no_model(asr_env):
    """A user has to be able to tell 'not configured' from 'broken'."""
    check = asr_env(None)
    assert "no ASR model" in check.hint
    assert "DCC_MCP_CAPCUT_ASR_EXECUTOR" in check.hint


def test_a_blank_executor_value_is_still_unconfigured(asr_env):
    check = asr_env("   ")
    assert check.status == doctor.WARN
    assert check.detail["configured"] is False


def test_a_configured_executor_is_ok(asr_env, tmp_path):
    executor = tmp_path / "transcribe.py"
    executor.write_text("print('')", encoding="utf-8")
    if os.name == "posix":
        executor.chmod(0o755)

    check = asr_env(executor)

    assert check.status == doctor.OK
    assert check.summary == f"ASR executor configured: {executor}"
    assert check.detail["usable"] is True
    assert check.detail["path"] == str(executor)
    assert check.hint is None


def test_a_path_that_is_not_a_file_is_a_warning_not_a_failure(asr_env, tmp_path):
    """Transcription is optional, so a misconfiguration must not fail the preflight."""
    check = asr_env(tmp_path / "absent.py")

    assert check.status == doctor.WARN
    assert "does not point at a file" in check.summary
    assert check.detail == {
        "configured": True,
        "path": str(tmp_path / "absent.py"),
        "usable": False,
    }
    assert check.hint


def test_a_directory_is_reported_as_unusable(asr_env, tmp_path):
    check = asr_env(tmp_path)
    assert check.status == doctor.WARN
    assert check.detail["usable"] is False


@pytest.mark.skipif(os.name != "posix", reason="the executable bit is a POSIX rule")
def test_a_non_executable_file_is_a_warning_that_says_chmod(asr_env, tmp_path):
    executor = tmp_path / "transcribe.py"
    executor.write_text("print('')", encoding="utf-8")
    executor.chmod(0o644)

    check = asr_env(executor)

    assert check.status == doctor.WARN
    assert "not executable" in check.summary
    assert "chmod +x" in check.summary


def test_the_asr_check_is_registered(pin_platform):
    assert "asr_executor" in [name for name, _ in doctor.CHECKS]


def test_the_asr_check_never_breaks_the_preflight(asr_env):
    """Whatever state the seam is in, the doctor still produces a verdict."""
    for value in (None, "   ", "C:/definitely/not/here.py"):
        check = asr_env(value)
        assert check.status in doctor.STATUSES
        assert check.status != doctor.FAIL
