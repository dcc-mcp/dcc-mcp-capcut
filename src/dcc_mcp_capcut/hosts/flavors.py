"""Host flavours: the shipped desktop editions of the ByteDance editor.

ByteDance publishes the same product line under two names: CapCut for
international channels and 剪映专业版 (JianyingPro) for the China channel. A
flavour is one shipped edition *as seen by one platform provider*, so the
Windows table and the macOS table describe the same two products through
different discovery facts (``.exe`` under an install root versus an ``.app``
bundle).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HostFlavor:
    """One shipped desktop edition, with the facts one platform needs.

    ``process_names`` is what the platform's window inventory reports for a
    running instance: ``CapCut.exe`` on Windows, ``CapCut`` on macOS. Matching
    is case-insensitive, so a flavour is identified by the executable or bundle
    name rather than by a localised window title.

    ``window_title`` pins the verified main-window title when one exists, and is
    ``None`` when the title is localised and varies by release. JianyingPro
    titles are localised on both platforms, so they are deliberately not pinned.
    """

    name: str
    package_id: str
    process_names: tuple[str, ...]
    window_title: str | None = None
    # Platform-specific discovery facts. Windows installs land under an
    # ``app_dir``; macOS ships an ``.app`` bundle at a known path.
    app_dir: str = ""
    exe: str = ""
    bundle_name: str = ""
    homepage: str = ""

    def matches_process(self, app_name: str) -> bool:
        """Return True when this window inventory entry belongs to the flavour."""
        normalized = str(app_name).casefold()
        return any(name.casefold() == normalized for name in self.process_names)

    def title_matches(self, window: dict[str, Any], *, bound: bool) -> bool:
        """Return True when the window's title is acceptable for this flavour."""
        if bound or self.window_title is None:
            # An explicit PID/handle binding is authoritative, and a flavour
            # without a pinned title is discriminated by its process name.
            return True
        return str(window.get("title", "")).casefold() == self.window_title.casefold()


def _existing(*paths: Path) -> list[Path]:
    """Drop unusable roots before they can produce a nonsense candidate."""
    return [path for path in paths if str(path) not in {".", ""}]


__all__ = ["HostFlavor"]
