"""Installation discovery and planning across every host provider.

The Windows assertions are the original contract and must not move. macOS and
Linux are new: macOS discovers an application bundle and offers only reviewable
install routes, and Linux states that it is unsupported rather than pretending
a package exists.
"""

import json
import os

import pytest

from dcc_mcp_capcut.hosts import LINUX, MACOS, WINDOWS, get_provider
from dcc_mcp_capcut.installer import HOST_FLAVORS, installation_plan, verify_installation


def test_every_platform_resolves_to_a_provider(pin_platform):
    for name, label in ((WINDOWS, "Windows"), (MACOS, "macOS"), (LINUX, "Linux")):
        provider = pin_platform(name)
        assert provider.name == name
        assert provider.label == label
    assert get_provider(WINDOWS).supported is True
    assert get_provider(MACOS).supported is True
    assert get_provider(LINUX).supported is False


def test_installation_plan_is_reviewable_and_does_not_execute(pin_platform):
    pin_platform("windows")
    plan = installation_plan()
    assert plan["installer"]["provider"] == "winget"
    assert plan["installer"]["package_id"] == "ByteDance.CapCut"
    assert plan["installer"]["requires_operator_confirmation"] is True
    assert "ui_control__system_operation" in plan["next_step"]


def test_verify_reports_not_ready_without_install_and_secret(pin_platform, monkeypatch):
    pin_platform("linux")
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


def test_detection_covers_both_host_flavours(pin_platform, monkeypatch, tmp_path):
    """CapCut (international) and 剪映专业版/JianyingPro (China) are both discoverable."""
    from dcc_mcp_capcut.installer import detect_installation

    pin_platform("windows")
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


def test_capcut_wins_when_both_flavours_are_installed(pin_platform, monkeypatch, tmp_path):
    """Detection stays deterministic: the international build is reported first."""
    from dcc_mcp_capcut.installer import detect_installation

    pin_platform("windows")
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
    for flavor in HOST_FLAVORS:
        command = flavor.install_command()
        assert command.startswith("winget install --id ")
        assert flavor.package_id in command
    # The pre-provider name stays available to existing callers.
    assert all(flavor.winget_command() == flavor.install_command() for flavor in HOST_FLAVORS)


# --------------------------------------------------------------------------
# macOS
# --------------------------------------------------------------------------


def test_macos_discovers_the_capcut_bundle(pin_platform, macos_applications):
    from dcc_mcp_capcut.installer import detect_installation

    bundle = macos_applications("CapCut.app", version="6.9.0", identifier="com.capcut.desktop")
    pin_platform("macos")

    found = detect_installation()
    assert found["installed"] is True
    assert found["flavor"] == "capcut"
    assert found["app_bundle"] == str(bundle)
    assert found["bundle_version"] == "6.9.0"
    assert found["bundle_identifier"] == "com.capcut.desktop"
    assert found["executable"].replace(os.sep, "/").endswith("Contents/MacOS/CapCut")
    assert found["provider"] == "macos"


def test_macos_discovers_jianyingpro_and_prefers_capcut(pin_platform, macos_applications):
    """Both macOS editions are discovered, with the same deterministic order."""
    from dcc_mcp_capcut.installer import detect_installation

    macos_applications("JianyingPro.app", version="6.8.0")
    pin_platform("macos")
    assert detect_installation()["flavor"] == "jianyingpro"

    macos_applications("CapCut.app", version="6.9.0")
    found = detect_installation()
    assert found["flavor"] == "capcut"
    assert found["supported"] is True


def test_macos_reports_a_bundle_without_a_readable_plist(pin_platform, macos_applications):
    """An installed-but-unreadable bundle is still installed."""
    from dcc_mcp_capcut.installer import detect_installation

    macos_applications("CapCut.app", version=None)
    pin_platform("macos")

    found = detect_installation()
    assert found["installed"] is True
    assert found["bundle_version"] is None


def test_macos_plan_offers_only_reviewable_install_routes(pin_platform, macos_applications):
    """No installer is ever run: the plan is evidence for an operator grant."""
    pin_platform("macos")
    plan = installation_plan()
    installer = plan["installer"]
    assert installer["requires_operator_confirmation"] is True
    assert installer["provider"] == "homebrew-cask"
    assert installer["command"] == "brew install --cask capcut"
    assert "https://www.capcut.com/" in installer["download_pages"]
    assert "ui_control__system_operation" in plan["next_step"]


def test_macos_jianyingpro_plan_falls_back_to_the_official_page(
    pin_platform, monkeypatch, macos_applications
):
    """Homebrew publishes no cask for 剪映专业版, so no command is invented."""
    from dcc_mcp_capcut.hosts import macos as macos_host

    macos_applications("JianyingPro.app", version="6.8.0")
    provider = pin_platform("macos")

    plan = provider.installation_plan()
    assert plan["installer"]["provider"] == "official-download"
    assert plan["installer"]["command"] is None
    assert "https://www.jianying.com/" in plan["installer"]["download_pages"]

    jianying = next(item for item in macos_host.MACOS_FLAVORS if item.name == "jianyingpro")
    assert jianying.install_command() is None


# --------------------------------------------------------------------------
# Linux
# --------------------------------------------------------------------------


def test_linux_detection_is_explicitly_unsupported(pin_platform):
    from dcc_mcp_capcut.installer import detect_installation

    pin_platform("linux")
    found = detect_installation()
    assert found["installed"] is False
    assert found["unsupported"] is True
    assert found["supported"] is False
    assert found["provider"] == "linux"
    assert "no official Linux client" in found["reason"]


def test_linux_plan_states_the_conclusion_instead_of_a_package(pin_platform):
    pin_platform("linux")
    plan = installation_plan()
    assert plan["status"] == "unsupported"
    assert plan["installer"] is None
    assert plan["supported_platforms"] == ["Windows", "macOS"]
    assert "Windows or macOS" in plan["next_step"]


def test_windows_candidates_are_never_relative_when_roots_are_unset(pin_platform, monkeypatch):
    """An unset install root must not produce a candidate relative to the CWD.

    Appending the install layout before dropping empty roots yielded
    ``CapCut\\Apps\\CapCut.exe``, which ``is_file()`` could match against a
    directory in whatever directory the adapter happened to start in.
    """
    pin_platform("windows")
    for name in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        monkeypatch.delenv(name, raising=False)

    for flavor in HOST_FLAVORS:
        assert flavor.candidate_paths() == []


def test_windows_candidate_layout_is_unchanged(pin_platform, monkeypatch, tmp_path):
    """The original three candidate roots, in the original order."""
    pin_platform("windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "pf"))
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "pf86"))

    assert [str(path) for path in HOST_FLAVORS[0].candidate_paths()] == [
        str(tmp_path / "local" / "CapCut" / "Apps" / "CapCut.exe"),
        str(tmp_path / "pf" / "CapCut" / "CapCut.exe"),
        str(tmp_path / "pf86" / "CapCut" / "CapCut.exe"),
    ]


def test_macos_degrades_on_a_malformed_plist(pin_platform, macos_applications, tmp_path):
    """A truncated XML plist must not crash discovery.

    XML plists parse through expat, whose ``ExpatError`` is not a
    ``ValueError``, so it escaped the "version unknown" fallback.
    """
    from dcc_mcp_capcut.hosts.macos import _read_bundle_metadata

    pin_platform("macos")
    bundle = macos_applications("CapCut.app", version=None)
    (bundle / "Contents" / "Info.plist").write_bytes(
        b'<?xml version="1.0"?><plist><dict><key>CFBundleShortVersionString</key>'
    )

    assert _read_bundle_metadata(bundle) == {}
    from dcc_mcp_capcut.installer import detect_installation

    assert detect_installation()["installed"] is True


@pytest.mark.parametrize("platform", [WINDOWS, MACOS, LINUX])
def test_every_plan_carries_the_bridge_environment_contract(pin_platform, platform):
    pin_platform(platform)
    plan = installation_plan()
    assert plan["environment"]["DCC_MCP_CAPCUT_INSTANCE_TYPE"] == "gui"
    assert plan["detection"]["provider"] == platform
    assert "status" in plan
