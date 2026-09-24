"""Platform providers for host binding.

Host binding used to be a set of hard-coded Windows assumptions scattered
across the installer, the window selection and the doctor. This package is the
seam: one provider per platform owns discovery, the reviewable install plan,
window-inventory matching and the doctor verdict, and every caller dispatches
through :func:`get_provider` instead of branching on ``os.name``.

Platform resolution reads ``os.name`` and ``sys.platform`` at call time rather
than at import time, so a process, a test or a doctor run can be pinned to a
provider without reimporting the module.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from .base import HostProvider
from .flavors import HostFlavor
from .linux import UNSUPPORTED_REASON, LinuxHostProvider
from .macos import ACCESSIBILITY_NOTE, MACOS_FLAVORS, MacOSHostProvider
from .versions import (
    SUPPORTED_HOST_VERSIONS,
    VERIFIED_BUILD,
    HostVersion,
    find_version,
    normalize_version,
    verified_builds,
    version_support,
    versions_for,
)
from .windows import PACKAGE_ID, WINDOWS_FLAVORS, WINGET_COMMAND, WindowsHostProvider

WINDOWS = "windows"
MACOS = "macos"
LINUX = "linux"

#: Platforms ByteDance actually publishes a desktop client for.
SUPPORTED_PLATFORMS = (WINDOWS, MACOS)
PLATFORMS = (WINDOWS, MACOS, LINUX)

_PROVIDERS: dict[str, type[HostProvider]] = {
    WINDOWS: WindowsHostProvider,
    MACOS: MacOSHostProvider,
    LINUX: LinuxHostProvider,
}

#: Explicit provider selection, set only by tests and diagnostics. Faking
#: ``os.name`` instead would silently change unrelated stdlib behaviour --
#: ``pathlib.Path`` picks its flavour from ``os.name`` when it is constructed.
_PLATFORM_OVERRIDE: str | None = None


def current_platform() -> str:
    """Resolve the running platform to a provider id."""
    if _PLATFORM_OVERRIDE is not None:
        return _PLATFORM_OVERRIDE
    if os.name == "nt":
        return WINDOWS
    if sys.platform == "darwin":
        return MACOS
    return LINUX


def set_platform(platform: str | None) -> None:
    """Force every caller onto one provider, or pass None to restore auto."""
    global _PLATFORM_OVERRIDE
    if platform is not None and platform not in _PROVIDERS:
        raise ValueError(f"unknown host platform {platform!r}; expected one of {PLATFORMS}")
    _PLATFORM_OVERRIDE = platform


def get_provider(platform: str | None = None) -> HostProvider:
    """Return the provider for ``platform``, defaulting to the running one."""
    resolved = platform or current_platform()
    try:
        return _PROVIDERS[resolved]()
    except KeyError as error:
        raise ValueError(
            f"unknown host platform {resolved!r}; expected one of {PLATFORMS}"
        ) from error


def host_flavors(platform: str | None = None) -> tuple[Any, ...]:
    """Return the editions discoverable on ``platform``."""
    return get_provider(platform).flavors


__all__ = [
    "ACCESSIBILITY_NOTE",
    "LINUX",
    "MACOS",
    "MACOS_FLAVORS",
    "PACKAGE_ID",
    "PLATFORMS",
    "SUPPORTED_HOST_VERSIONS",
    "SUPPORTED_PLATFORMS",
    "UNSUPPORTED_REASON",
    "WINDOWS",
    "VERIFIED_BUILD",
    "WINDOWS_FLAVORS",
    "WINGET_COMMAND",
    "HostFlavor",
    "HostProvider",
    "HostVersion",
    "LinuxHostProvider",
    "MacOSHostProvider",
    "WindowsHostProvider",
    "current_platform",
    "find_version",
    "get_provider",
    "host_flavors",
    "normalize_version",
    "verified_builds",
    "version_support",
    "versions_for",
]
