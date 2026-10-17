"""The one place the adapter decides how a child process gets a console.

Every shell-out in this package goes through :func:`run_hidden` instead of
calling :func:`subprocess.run` directly. On Windows a child launched from a
process with no console -- an MCP server started by a desktop client, which is
the normal case here -- is given a brand new console window, which flashes and
can steal foreground focus. The CUA route shells out roughly four times per
action, and its own contract is that delivery never pre-empts the foreground, so
that flash is not cosmetic noise: it contradicts the contract.

``CREATE_NO_WINDOW`` suppresses the new console. The attribute only exists on
Windows, so it is read through :func:`getattr` with a ``0`` default; on POSIX
the flag is a no-op and every other argument passes through untouched.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from typing import Any

#: Suppresses the console Windows would otherwise create for a child of a
#: console-less parent. ``0`` on every other platform, where the flag is inert.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_hidden(args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """Run one fixed argv without letting Windows open a console for it.

    A pass-through to :func:`subprocess.run` that injects ``creationflags``. A
    caller that passes ``creationflags`` explicitly wins -- the injection is a
    default, not an override -- but nothing in this package needs to.
    """
    kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.run(list(args), **kwargs)  # noqa: S603 - fixed argv, never a shell
