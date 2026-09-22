"""Shared fixtures for the test suite.

Host binding dispatches through a platform provider. Tests that describe one
platform's facts -- Windows ``.exe`` names, macOS application bundles, the Linux
``unsupported`` verdict -- pin the provider explicitly instead of inheriting
whatever machine pytest runs on, because CI runs all three.

The pin goes through ``hosts.set_platform`` rather than a patched ``os.name``:
``pathlib.Path`` chooses its flavour from ``os.name`` at construction time, so
faking ``os.name`` on a non-native platform makes unrelated path code explode.
"""

from __future__ import annotations

import pytest

from dcc_mcp_capcut.hosts import get_provider, set_platform


@pytest.fixture
def pin_platform(monkeypatch):
    """Pin the process to one host provider and return it."""

    def _pin(name: str):
        monkeypatch.setattr("dcc_mcp_capcut.hosts._PLATFORM_OVERRIDE", name, raising=False)
        provider = get_provider()
        assert provider.name == name, f"expected the {name} provider, got {provider.name}"
        return provider

    return _pin


@pytest.fixture(autouse=True)
def _restore_platform():
    """Never leak a pinned provider into another test."""
    yield
    set_platform(None)


@pytest.fixture
def macos_applications(tmp_path, monkeypatch):
    """Point macOS bundle discovery at a temporary applications root.

    Returns a factory that materialises an ``.app`` bundle the way macOS lays
    one out, including the ``Info.plist`` the provider reads for version
    evidence.
    """

    def _make(bundle_name: str, *, version: str | None = "6.9.0", identifier: str | None = None):
        import plistlib

        from dcc_mcp_capcut.hosts import macos as macos_host

        root = tmp_path / "Applications"
        root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(macos_host, "APPLICATION_ROOTS", (str(root),))

        bundle = root / bundle_name
        (bundle / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
        (bundle / "Contents" / "MacOS" / bundle_name[: -len(".app")]).write_bytes(b"")
        if version is not None or identifier is not None:
            info: dict[str, object] = {}
            if version is not None:
                info["CFBundleShortVersionString"] = version
                info["CFBundleVersion"] = f"{version}.1"
            if identifier is not None:
                info["CFBundleIdentifier"] = identifier
            (bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
        return bundle

    return _make
