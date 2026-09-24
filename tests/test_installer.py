"""Installation discovery and planning across every host provider.

The Windows assertions are the original contract and must not move. macOS and
Linux are new: macOS discovers an application bundle and offers only reviewable
install routes, and Linux states that it is unsupported rather than pretending
a package exists.
"""

import json
import os
import plistlib
import sys
from random import Random

import pytest

from dcc_mcp_capcut import hosts
from dcc_mcp_capcut.bridge import DEFAULT_BRIDGE_TOKEN
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


@pytest.mark.parametrize(
    "os_name, sys_platform, expected",
    [
        ("nt", "win32", WINDOWS),
        # os.name is the primary discriminator: nt is Windows even when
        # sys.platform disagrees, which is what keeps the doctor honest on a
        # Windows box running a posix-flavoured test double.
        ("nt", "linux", WINDOWS),
        ("posix", "darwin", MACOS),
        ("posix", "linux", LINUX),
        ("posix", "cygwin", LINUX),
        ("posix", "freebsd13", LINUX),
        # An unrecognised posix platform falls back to Linux rather than
        # raising: the doctor must still run and report unsupported.
        ("posix", "sunos5", LINUX),
    ],
)
def test_auto_detection_reads_the_running_platform(monkeypatch, os_name, sys_platform, expected):
    """Cover the real dispatch path, not just set_platform overrides.

    Every other test pins the provider explicitly, so nothing exercised the
    os.name/sys.platform branch that production actually takes.
    """
    monkeypatch.setattr(os, "name", os_name)
    monkeypatch.setattr(sys, "platform", sys_platform)
    assert hosts.current_platform() == expected
    assert get_provider().name == expected


def test_the_hosts_subpackage_ships_with_the_adapter():
    """`hosts` is the first Python subpackage in this repo.

    The rest of the package is flat, so there was no precedent guaranteeing the
    wheel picks it up; a missing file would only surface at install time on an
    operator's machine. Import every module through the package to prove the
    subpackage resolves as installed data, not as a source-tree accident.
    """
    from importlib.resources import files

    root = files("dcc_mcp_capcut")
    for module in ("__init__", "base", "flavors", "linux", "macos", "windows"):
        assert root.joinpath(f"hosts/{module}.py").is_file(), module

    import dcc_mcp_capcut.hosts as hosts_package

    for name in ("base", "flavors", "linux", "macos", "windows"):
        __import__(f"dcc_mcp_capcut.hosts.{name}")
    assert hosts_package.current_platform() in hosts_package.PLATFORMS


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
    # The probe now always runs; keep this test off the real loopback port.
    monkeypatch.setattr(
        "dcc_mcp_capcut.installer.urlopen",
        lambda *_args, **_kwargs: _Response({"ok": True, "panel_connected": True}),
    )
    result = verify_installation()
    assert result["bridge_token_configured"] is False
    assert result["ready"] is False


def test_verify_probes_health_with_the_default_token_when_unset(pin_platform, monkeypatch):
    # An unset token used to skip the probe entirely, so a running bridge was
    # reported as unreachable with a null error. The probe must use the same
    # default token call_bridge uses.
    pin_platform("linux")
    monkeypatch.delenv("DCC_MCP_CAPCUT_BRIDGE_TOKEN", raising=False)
    sent = {}

    def fake_urlopen(request, *_args, **_kwargs):
        sent["token"] = request.get_header("X-dcc-mcp-token")
        return _Response({"ok": True, "panel_connected": False})

    monkeypatch.setattr("dcc_mcp_capcut.installer.urlopen", fake_urlopen)

    result = verify_installation()

    assert sent["token"] == DEFAULT_BRIDGE_TOKEN
    assert result["bridge_reachable"] is True
    assert result["panel_connected"] is False
    assert result["bridge_error"] is None
    # A default token is not operator configuration, but it is also not a
    # readiness fault: readiness is false here because Linux has no host to
    # bind, not because the token is weak.
    assert result["bridge_token_configured"] is False
    assert result["token_is_default"] is True
    assert result["ready"] is False


def test_verify_records_an_empty_bridge_url_as_evidence_not_an_exception(monkeypatch):
    # An explicit empty DCC_MCP_CAPCUT_BRIDGE_URL makes Request() reject the
    # URL before a socket is opened. That is diagnostic evidence, so it must
    # land in bridge_error instead of escaping to the caller.
    monkeypatch.setenv("DCC_MCP_CAPCUT_BRIDGE_URL", "")
    monkeypatch.delenv("DCC_MCP_CAPCUT_BRIDGE_TOKEN", raising=False)

    result = verify_installation()

    assert result["bridge_reachable"] is False
    assert result["bridge_error"]
    assert "unknown url type" in result["bridge_error"]
    assert result["ready"] is False


@pytest.mark.parametrize("payload", [[], "hello", None])
def test_verify_records_a_non_object_health_payload(monkeypatch, payload):
    # The doctor probes /health precisely when the port is held by another
    # process, so a non-object reply is realistic rather than hypothetical.
    monkeypatch.setenv("DCC_MCP_CAPCUT_BRIDGE_TOKEN", "secret")

    def fake_urlopen(request, *_args, **_kwargs):
        return _Response(payload)

    monkeypatch.setattr("dcc_mcp_capcut.installer.urlopen", fake_urlopen)

    result = verify_installation()

    assert result["bridge_reachable"] is False
    assert "unexpected /health payload" in result["bridge_error"]
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


@pytest.fixture
def _ready_host(monkeypatch):
    """A host that is installed, bound and serving a connected panel.

    Every readiness factor except the token is satisfied, so a ``ready``
    verdict isolates what the token alone does to it.
    """
    monkeypatch.setenv("DCC_MCP_CAPCUT_BRIDGE_URL", "http://127.0.0.1:47410")
    monkeypatch.setenv("DCC_MCP_CAPCUT_PID", "31776")
    monkeypatch.setenv("DCC_MCP_CAPCUT_WINDOW_HANDLE", "106895862")
    monkeypatch.setattr(
        "dcc_mcp_capcut.installer.detect_installation",
        lambda: {"installed": True, "executable": "CapCut.exe"},
    )
    monkeypatch.setattr(
        "dcc_mcp_capcut.installer.urlopen",
        lambda *_args, **_kwargs: _Response({"ok": True, "panel_connected": True}),
    )


@pytest.mark.parametrize(
    "token, configured, default",
    [
        # Unset: no operator token, and the default is therefore in force.
        (None, False, True),
        (DEFAULT_BRIDGE_TOKEN, True, True),
        ("s" * 43, True, False),
    ],
)
def test_verify_records_both_token_facts_and_a_default_token_never_vetoes_readiness(
    pin_platform, monkeypatch, _ready_host, token, configured, default
):
    """``token_is_default`` coexists with ``configured`` and never decides ``ready``.

    ``ready`` asks whether the adapter can bind this host and reach the panel
    on the token actually in force, and the documented default is a token that
    works. A weak token is a security warning the doctor grades as ``warn``
    through ``check_bridge_token``; making it fail readiness would overstate
    that as a wiring fault.
    """
    pin_platform("windows")
    if token is None:
        monkeypatch.delenv("DCC_MCP_CAPCUT_BRIDGE_TOKEN", raising=False)
    else:
        monkeypatch.setenv("DCC_MCP_CAPCUT_BRIDGE_TOKEN", token)

    result = verify_installation()

    assert result["bridge_token_configured"] is configured
    assert result["token_is_default"] is default
    assert result["ready"] is True


def test_verify_is_json_serialisable_with_the_version_matrix_attached(
    pin_platform, monkeypatch, _ready_host
):
    """The doctor serialises this evidence with ``--json``; it must not carry a Path.

    The stub carries the provider's real version payload, so the matrix fields
    this test is named for actually pass through ``verify_installation()``.
    """
    provider = pin_platform("windows")
    monkeypatch.setenv("DCC_MCP_CAPCUT_BRIDGE_TOKEN", "s" * 43)
    monkeypatch.setattr(
        "dcc_mcp_capcut.installer.detect_installation",
        lambda: {
            "installed": True,
            "executable": "CapCut.exe",
            **provider.version_evidence("capcut"),
        },
    )

    payload = verify_installation()

    assert payload["version_support"]["status"] == "undetermined"
    assert json.loads(json.dumps(payload)) == payload
    assert json.loads(json.dumps(payload))["ready"] is True


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


def _write_plist(bundle, data):
    (bundle / "Contents" / "Info.plist").write_bytes(data)
    return bundle


@pytest.mark.parametrize(
    "label, payload",
    [
        ("truncated-xml", b'<?xml version="1.0"?><plist><dict><key>CFBundleName</key>'),
        ("empty", b""),
        ("plain-text", b"this is not a plist at all"),
        ("xml-header-only", b'<?xml version="1.0"?>'),
        ("truncated-binary", plistlib.dumps({"A": "b"}, fmt=plistlib.FMT_BINARY)[:12]),
        ("bare-binary-header", b"bplist00"),
        # Mutating the encoding declaration raises LookupError, which is not a
        # ValueError or ExpatError and so escaped the original fallback.
        (
            "bad-xml-encoding",
            b'<?xml version="1.0" encoding="UTFD8"?>\n<plist version="1.0"><dict/></plist>',
        ),
    ],
)
def test_macos_degrades_on_an_unreadable_plist(pin_platform, macos_applications, label, payload):
    """Discovery must never fail because a bundle's plist is unreadable.

    The docstring promises that every failure degrades to "version unknown",
    and callers rely on it: a raised error surfaces to an agent through
    ``detect_installation`` and makes the doctor report a bug in itself for an
    application that is in fact installed.
    """
    from dcc_mcp_capcut.hosts.macos import _read_bundle_metadata

    pin_platform("macos")
    bundle = _write_plist(macos_applications("CapCut.app", version=None), payload)
    assert _read_bundle_metadata(bundle) == {}, label

    from dcc_mcp_capcut.installer import detect_installation

    assert detect_installation()["installed"] is True


def test_macos_survives_corrupted_plists_found_by_fuzzing(pin_platform, macos_applications):
    """Bounded, seeded mutation of a real plist: no mutation may raise.

    A single hand-picked malformed sample only locks in the failure shape that
    was already known. Fuzzing found two more -- ``IndexError`` from a corrupt
    object table and ``LookupError: unknown encoding`` -- so the regression
    test sweeps the class rather than one instance. The seed and the bound keep
    it deterministic and fast; the binary format is deliberately left out
    because a corrupt binary header makes plistlib attempt a huge allocation,
    which is covered by the broad handler but is not safe to exercise in CI.
    """
    from dcc_mcp_capcut.hosts.macos import _read_bundle_metadata

    pin_platform("macos")
    bundle = macos_applications("CapCut.app", version=None)
    good = plistlib.dumps(
        {"CFBundleShortVersionString": "6.9.0", "CFBundleIdentifier": "com.capcut.desktop"},
        fmt=plistlib.FMT_XML,
    )
    random = Random(20240922)
    for attempt in range(300):
        mutated = bytearray(good)
        for _ in range(random.randint(1, 3)):
            mutated[random.randrange(len(mutated))] = random.randrange(256)
        _write_plist(bundle, bytes(mutated))
        # The contract is "never raise": a mutation that still parses is free
        # to return real metadata, so only the type is pinned here.
        assert isinstance(_read_bundle_metadata(bundle), dict), attempt


def test_macos_reads_an_xml_plist(pin_platform, macos_applications):
    """The XML format parses too, not just the binary one the fixture writes.

    The fuzzing gap existed because only one format was exercised: the fixture
    writes binary, while a real bundle may ship either.
    """
    from dcc_mcp_capcut.hosts.macos import _read_bundle_metadata

    pin_platform("macos")
    bundle = macos_applications("CapCut.app", version=None)
    _write_plist(
        bundle,
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<plist version="1.0"><dict>'
        b"<key>CFBundleShortVersionString</key><string>6.9.0</string>"
        b"<key>CFBundleIdentifier</key><string>com.capcut.desktop</string>"
        b"</dict></plist>",
    )

    metadata = _read_bundle_metadata(bundle)
    assert metadata["bundle_version"] == "6.9.0"
    assert metadata["bundle_identifier"] == "com.capcut.desktop"


@pytest.mark.parametrize("platform", [WINDOWS, MACOS, LINUX])
def test_every_plan_carries_the_bridge_environment_contract(pin_platform, platform):
    pin_platform(platform)
    plan = installation_plan()
    assert plan["environment"]["DCC_MCP_CAPCUT_INSTANCE_TYPE"] == "gui"
    assert plan["detection"]["provider"] == platform
    assert "status" in plan
