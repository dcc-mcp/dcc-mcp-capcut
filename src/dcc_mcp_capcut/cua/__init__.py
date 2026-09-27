"""A thin dcc-cua execution adapter for the pixel route.

The CapCut host surface is a single opaque QML canvas: the window inventory
reports one node with no children and the driver treats the missing
accessibility provider as **permanent** for the window class. Semantic
automation is therefore not merely hard, it is closed, and the only route left
is the one this package implements --

    exact PID/HWND binding -> pixel snapshot -> coordinate input -> verify

Tool code keeps emitting typed actions, one per call, exactly as it does for the
host bridge. :func:`execute` is the whole translation layer: it binds, captures
the frame the coordinates will be measured in, delivers the input, and verifies
the resulting state.

What this package is not:

- **Not headless.** Unattended here means unattended on an *interactive*
  Windows or macOS desktop. A locked workstation or a Linux CI runner has no
  desktop to drive, and :func:`execute` says so instead of timing out later.
- **Not a host-bridge replacement.** The bridge stays the typed, auditable path
  for everything the panel can reach. This route exists for what the panel
  cannot reach, and it is last, not first.
- **Not proof by pixels.** A changed pixel digest proves the window *changed*.
  It does not prove the *intended* change happened -- a dialog appearing and the
  requested edit landing look identical from a digest -- so it is reported as
  evidence and never allowed to satisfy :func:`verify`.

Red lines preserved from the spike: no injection into the host process, no
redistribution of official files, no automatic upload, no decryption of
JianYing 6.0+ drafts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from . import actions, cli, guards, surface
from .errors import CuaError, CuaVerificationError
from .guards import (
    InstallTreeDiff,
    InstallTreeGuard,
    VersionGuard,
    guard_host_version,
    install_root,
    snapshot_install_tree,
)
from .surface import CuaBinding, CuaSnapshot, CuaVerification, bind, snapshot, verify

__all__ = [
    "actions",
    "cli",
    "guards",
    "surface",
    # surface
    "CuaBinding",
    "CuaSnapshot",
    "CuaVerification",
    "CuaExecution",
    "bind",
    "snapshot",
    "verify",
    "execute",
    "bind_and_check",
    # guards
    "InstallTreeGuard",
    "InstallTreeDiff",
    "VersionGuard",
    "guard_host_version",
    "snapshot_install_tree",
    "install_root",
    # errors
    "CuaError",
]


@dataclass(frozen=True)
class CuaExecution:
    """One executed typed action, with everything needed to audit it.

    ``ok`` mirrors the verification verdict alone. ``pixel_changed`` is carried
    next to it, never folded into it: the two facts answer different questions
    and a receipt that conflates them would let a changed pixel stand in for a
    verified edit.
    """

    action: str
    binding: CuaBinding
    delivery: dict[str, Any] = field(default_factory=dict)
    before: CuaSnapshot | None = None
    after: CuaSnapshot | None = None
    #: True when the two captures differ. Evidence that *something* changed --
    #: not evidence that the requested change happened.
    pixel_changed: bool = False
    verification: CuaVerification | None = None
    #: True when the caller asked for verification and none was possible.
    verified: bool = False
    ok: bool = False
    #: The verdict the run was admitted under, so a receipt is self-describing
    #: about whether its coordinates were validated for this build.
    version_guard: VersionGuard | None = None
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "binding": self.binding.as_dict(),
            "delivery": self.delivery,
            "before": self.before.as_dict() if self.before else None,
            "after": self.after.as_dict() if self.after else None,
            "pixel_changed": self.pixel_changed,
            "verification": self.verification.as_dict() if self.verification else None,
            "verified": self.verified,
            "ok": self.ok,
            "version_guard": self.version_guard.as_dict() if self.version_guard else None,
            "notes": list(self.notes),
        }


def bind_and_check(
    *,
    pid: int | None = None,
    window_handle: int | None = None,
    allow_unverified: bool = False,
    timeout: float = cli.DEFAULT_TIMEOUT,
) -> tuple[CuaBinding, VersionGuard]:
    """Bind one exact window and grade the build it belongs to, together.

    These two belong in one call because the version verdict is what makes the
    binding safe to use: a coordinate set measured on one build is not valid on
    another, so a caller that binds without grading would hold an exact PID for
    a window its coordinates do not describe.

    The guard is the same one :func:`execute` enforces, so binding here and
    executing later cannot disagree about whether the build was admissible.
    """
    guard = _enforce_version_guard(allow_unverified)
    return bind(pid=pid, window_handle=window_handle, timeout=timeout), guard


def _enforce_version_guard(allow_unverified: bool) -> VersionGuard:
    """Refuse to run unless the installed build is one coordinates were measured on.

    This runs on the main :func:`execute` path, not only in
    :func:`bind_and_check`, because the guarantee the docs make is unconditional:
    a caller that reaches ``execute()`` by any route must not silently replay
    coordinates on a build nobody measured them on.
    """
    guard = guard_host_version(allow_unverified=allow_unverified)
    if not guard.allowed:
        raise CuaError(
            f"refusing to run pixel execution on an {guard.status} build "
            f"({guard.edition} {guard.version or 'unknown'}); {guard.hint}"
        )
    return guard


def execute(
    action: str,
    params: Mapping[str, Any] | None = None,
    *,
    binding: CuaBinding | None = None,
    expectations: Sequence[Mapping[str, Any]] | None = None,
    capture_after: bool = True,
    allow_foreground: bool = True,
    allow_unverified: bool = False,
    timeout: float = cli.DEFAULT_TIMEOUT,
    verify_timeout_ms: int | None = None,
) -> CuaExecution:
    """Run one typed action through bind -> snapshot -> input -> verify.

    ``expectations`` is what "verify" means for this call. Omitting it is
    allowed, and the receipt then says ``verified=False`` -- an unasked-for
    verification is not silently invented, and an unverified action is not
    reported as a success.

    The version guard runs before anything else, and it runs whether or not a
    ``binding`` was supplied: a coordinate is a fact about one build, so a caller
    holding an exact PID for a window its coordinates do not describe is exactly
    the failure this refuses. ``allow_unverified=True`` proceeds on an unlisted
    build as an explicit acknowledgement, and the receipt records that it did.

    On failure the exception still describes how far the run got, because the
    residue matters: an action that was delivered and could not be verified has
    already changed the project, and the operator needs to know that.
    """
    surface.require_interactive_platform()
    guard = _enforce_version_guard(allow_unverified)
    binding = binding if binding is not None else bind(timeout=timeout)

    before = snapshot(binding, timeout=timeout)
    delivery = surface.act(
        binding,
        action,
        params,
        observation=before,
        allow_foreground=allow_foreground,
        timeout=timeout,
    )
    after = snapshot(binding, timeout=timeout) if capture_after else None

    pixel_changed = bool(
        after is not None
        and before.content_digest is not None
        and after.content_digest is not None
        and before.content_digest != after.content_digest
    )
    notes: list[str] = []
    if after is not None and before.content_digest is None:
        notes.append(
            "the driver returned no pixel digest; change detection is unavailable for this run"
        )
    if guard.status != guards.PINNED:
        # Reachable only via allow_unverified=True. Recorded so a receipt says
        # the coordinates were unvalidated for this build, rather than leaving
        # an operator to assume they were checked.
        notes.append(
            f"ran on an {guard.status} build ({guard.edition} {guard.version or 'unknown'}) "
            "by explicit opt-in; coordinates are unvalidated for this build"
        )

    verification: CuaVerification | None = None
    if expectations:
        try:
            verification = verify(
                binding, expectations, timeout_ms=verify_timeout_ms, timeout=timeout
            )
        except CuaVerificationError as error:
            # The unproven path is the one where the residue matters most: input
            # was already delivered, so the project may already have changed.
            # Attach the receipt to the exception instead of letting it die with
            # the stack frame that built it.
            error.execution = _execution(
                action=action,
                binding=binding,
                delivery=delivery,
                before=before,
                after=after,
                pixel_changed=pixel_changed,
                verification=None,
                notes=notes,
                guard=guard,
            )
            raise

    return _execution(
        action=action,
        binding=binding,
        delivery=delivery,
        before=before,
        after=after,
        pixel_changed=pixel_changed,
        verification=verification,
        notes=notes,
        guard=guard,
    )


def _execution(
    *, action, binding, delivery, before, after, pixel_changed, verification, notes, guard
) -> CuaExecution:
    """Build the receipt, including the version verdict it ran under."""
    return CuaExecution(
        action=action,
        binding=binding,
        delivery=delivery,
        before=before,
        after=after,
        pixel_changed=pixel_changed,
        verification=verification,
        verified=verification is not None and verification.proven,
        ok=verification.proven if verification is not None else False,
        version_guard=guard,
        notes=tuple(notes),
    )
