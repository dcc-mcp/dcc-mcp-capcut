"""Version guard and install-tree snapshot: the two facts a pixel run is pinned to.

Pixel automation is only valid against the build it was measured on. A
coordinate is a fact about one rendered frame -- a function of the build, the
display scale and the window size -- so unlike a host-bridge action it does not
survive a version change. These two guards make that dependency explicit and
checkable instead of leaving it to a failing click.

**Version guard.** The support matrix in
:mod:`dcc_mcp_capcut.hosts.versions` is the one source of truth for which builds
are known. The doctor grades an unlisted build as a warning, because the adapter
still *binds and starts* on one. The execution layer is stricter on purpose: it
refuses to replay coordinates against a build nobody measured them on unless the
caller opts in, because "the adapter ran" and "the click landed on the control
the operator meant" are different claims.

**Install-tree snapshot.** CapCut upgrades itself in place. Measured live, a
9.5.0.4050 launch deleted the 9.4.0.4015 install directory it was replacing, so
an install tree is not a stable fact and a binding taken across an upgrade can
name a process that no longer exists. Snapshotting the tree before launch and
diffing it afterwards turns "the environment drifted" into a reportable event
with the paths that moved.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..hosts import get_provider
from ..hosts.versions import KNOWN, UNDETERMINED, UNKNOWN, VERIFIED, HostVersion

#: Verdicts the version guard reports.
PINNED = "pinned"  # the build is listed, so coordinates measured on it are meaningful
UNPINNED = "unpinned"  # the build is unlisted or unread; coordinates are unvalidated here
NO_HOST = "no_host"  # nothing installed, so there is no build to grade
UNSUPPORTED_PLATFORM = "unsupported_platform"

#: Bounds on the install-tree walk. An install tree can hold tens of thousands
#: of files; an unbounded walk would turn a preflight check into the slowest
#: part of a launch.
MAX_FILES = 20_000
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class VersionGuard:
    """The outcome of grading the installed build for pixel execution."""

    status: str
    edition: str | None
    version: str | None
    support: dict[str, Any] = field(default_factory=dict)
    #: True when a coordinate run may proceed without an explicit opt-in.
    allowed: bool = False
    hint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "edition": self.edition,
            "version": self.version,
            "allowed": self.allowed,
            "support": self.support,
            "hint": self.hint,
        }


def guard_host_version(
    *, allow_unverified: bool = False, platform: str | None = None
) -> VersionGuard:
    """Grade the installed build and decide whether pixel execution may proceed.

    A listed build (``verified`` or merely ``known``) is *pinned*: the matrix
    records it, so it is a build coordinates could have been measured on at all.
    That is a fact about the build, **not** about any coordinate. Being listed
    does not make a coordinate correct, and it does not make the frame check
    redundant: a coordinate is only meaningful once it was measured on this build
    *and* checked against the captured frame, which are two different questions
    answered by two different guards. "The adapter ran" and "the click landed on
    the control the operator meant" remain different claims here.

    An unlisted or unreadable build is *unpinned* and is refused unless
    ``allow_unverified`` is set -- an explicit operator acknowledgement that
    they are running coordinates nobody validated for this build.
    """
    provider = get_provider(platform)
    if not provider.supported:
        return VersionGuard(
            status=UNSUPPORTED_PLATFORM,
            edition=None,
            version=None,
            support={"platform": provider.name},
            allowed=False,
            hint=f"CapCut ships no official {provider.label} client.",
        )

    detection = provider.detect_installation()
    support = dict(detection.get("version_support") or {})
    edition = detection.get("flavor")
    version = support.get("version")
    status = support.get("status", UNDETERMINED)

    if not detection.get("installed"):
        return VersionGuard(
            status=NO_HOST,
            edition=edition,
            version=version,
            support=support,
            allowed=False,
            hint=f"no host installation found on {provider.label}",
        )

    listed = status in (VERIFIED, KNOWN)
    if listed:
        return VersionGuard(
            status=PINNED,
            edition=edition,
            version=version,
            support=support,
            allowed=True,
            hint=support.get("hint"),
        )

    reason = (
        f"{edition} {version or 'unknown'} on {provider.label} is not in the verified host matrix"
        if status == UNKNOWN
        else f"the installed {edition} version on {provider.label} could not be read"
    )
    return VersionGuard(
        status=UNPINNED,
        edition=edition,
        version=version,
        support=support,
        allowed=allow_unverified,
        hint=(
            f"{reason}. Pixel coordinates are measured per build, so a run on this build "
            "is unvalidated; record the version, or pass allow_unverified=True to proceed "
            "knowingly."
        ),
    )


# --- install tree ----------------------------------------------------------


@dataclass(frozen=True)
class InstallTreeSnapshot:
    """A bounded fingerprint of one install tree.

    Entries are ``(relative path, size, mtime_ns)`` triples, sorted, and
    ``digest`` is the SHA-256 of that serialisation -- so two snapshots can be
    compared by digest or diffed entry by entry without holding a tree in memory.
    """

    root: str
    entries: tuple[tuple[str, int, int], ...] = ()
    file_count: int = 0
    total_bytes: int = 0
    digest: str = ""
    #: True when the walk hit :data:`MAX_FILES` and stopped early. A truncated
    #: snapshot is still comparable -- the same walk on the same tree yields the
    #: same prefix -- but it must say so rather than imply full coverage.
    truncated: bool = False
    exists: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "digest": self.digest,
            "truncated": self.truncated,
            "exists": self.exists,
        }


@dataclass(frozen=True)
class InstallTreeDiff:
    """What changed between two snapshots of one install tree."""

    before: InstallTreeSnapshot
    after: InstallTreeSnapshot
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()

    @property
    def roots_match(self) -> bool:
        """True when both snapshots describe the same install root.

        Two different roots are not a diff at all -- the install moved. Callers
        rely on this to tell "the tree drifted" from "the tree is somewhere
        else now", so it is part of the result rather than something each caller
        has to rediscover.
        """
        return bool(self.before.root) and self.before.root == self.after.root

    @property
    def unchanged(self) -> bool:
        """True when both trees were read, at one root, and nothing differs.

        A changed root is not "unchanged": the install directory itself moved,
        which is a stronger statement than any file-level diff.
        """
        return (
            self.before.exists
            and self.after.exists
            and self.roots_match
            and not (self.added or self.removed or self.changed)
        )

    @property
    def host_replaced(self) -> bool:
        """True when the install tree vanished, moved, or was largely removed.

        This is the shape of the observed self-upgrade: CapCut deleted the
        previous version's install directory during launch. A binding taken
        before that event names a process that may no longer exist, so the caller
        must rebind rather than trust the ids it holds.

        A different root counts as a replacement -- the install did not stay put,
        which is exactly the fact that invalidates a binding. The removal
        threshold is strict majority, so a tree that lost only a few files is
        drift, not a replacement. A single-file tree cannot express "largely
        removed" at all, so it falls back to whether the file itself survived.
        """
        if not self.after.exists or not self.before.exists:
            return True
        if not self.roots_match:
            return True
        if not self.before.file_count:
            return False
        if self.before.file_count < 2:
            return bool(self.removed)
        return len(self.removed) > self.before.file_count // 2

    def as_dict(self) -> dict[str, Any]:
        return {
            "before": self.before.as_dict(),
            "after": self.after.as_dict(),
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": list(self.changed),
            "unchanged": self.unchanged,
            "roots_match": self.roots_match,
            "host_replaced": self.host_replaced,
        }


def install_root(*, platform: str | None = None) -> Path | None:
    """The directory an install tree snapshot walks.

    Discovery returns the *executable* (a Windows ``.exe``, or the Mach-O binary
    inside a macOS bundle); the tree that matters is the one *containing* it. On
    Windows that is the flavour directory holding ``Apps``; on macOS it is the
    ``.app`` bundle itself.
    """
    detection = get_provider(platform).detect_installation()
    executable = detection.get("executable")
    if not executable:
        return None
    path = Path(str(executable))
    if path.parent.name == "Apps":
        # The per-user layout nests the binary one level below the install root.
        return path.parent.parent
    if path.suffix == ".app":
        return path
    # A macOS bundle is named ``<name>.app``; the binary sits several levels
    # inside it, so the bundle is the outermost component ending in ``.app``.
    # Matching the literal string ``.app`` against the parts would never hit,
    # because the part is the whole name.
    for index, part in enumerate(path.parts):
        if part.endswith(".app"):
            return Path(*path.parts[: index + 1])
    return path.parent


def snapshot_install_tree(
    root: Path | str | None = None, *, platform: str | None = None
) -> InstallTreeSnapshot:
    """Fingerprint the install tree, bounded by :data:`MAX_FILES`.

    A missing root is a result, not an error: "the install is gone" is exactly
    the fact this snapshot exists to record, and raising would hide it.
    """
    resolved = Path(root) if root is not None else install_root(platform=platform)
    if resolved is None:
        return InstallTreeSnapshot(root="", exists=False)
    resolved = Path(resolved)
    if not resolved.exists():
        return InstallTreeSnapshot(root=str(resolved), exists=False)

    entries: list[tuple[str, int, int]] = []
    total = 0
    truncated = False
    for dirpath, dirnames, filenames in os.walk(resolved):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            try:
                stat = path.stat()
            except OSError:
                # A file the installer is actively replacing can vanish between
                # listing and stat. Skipping it is honest; the digest is a
                # fingerprint, not an inventory.
                continue
            entries.append(
                (str(path.relative_to(resolved)).replace("\\", "/"), stat.st_size, stat.st_mtime_ns)
            )
            total += stat.st_size
            if len(entries) >= MAX_FILES or total >= MAX_TOTAL_BYTES:
                truncated = True
                break
        if truncated:
            break

    entries.sort()
    payload = "\n".join(f"{name}\t{size}\t{mtime}" for name, size, mtime in entries)
    return InstallTreeSnapshot(
        root=str(resolved),
        entries=tuple(entries),
        file_count=len(entries),
        total_bytes=total,
        digest=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        truncated=truncated,
        exists=True,
    )


def diff_install_tree(before: InstallTreeSnapshot, after: InstallTreeSnapshot) -> InstallTreeDiff:
    """Compare two snapshots of the same tree."""
    if before.root and after.root and before.root != after.root:
        # Different roots means the install moved, not that files drifted.
        return InstallTreeDiff(before=before, after=after)

    before_files = {name: (size, mtime) for name, size, mtime in before.entries}
    after_files = {name: (size, mtime) for name, size, mtime in after.entries}
    added = tuple(sorted(set(after_files) - set(before_files)))
    removed = tuple(sorted(set(before_files) - set(after_files)))
    changed = tuple(
        sorted(
            name
            for name in set(before_files) & set(after_files)
            if before_files[name] != after_files[name]
        )
    )
    return InstallTreeDiff(
        before=before, after=after, added=added, removed=removed, changed=changed
    )


@dataclass
class InstallTreeGuard:
    """A pre-launch snapshot plus the post-launch recheck that proves drift.

    Used around a launch, which is the window in which CapCut is known to rewrite
    its own install tree:

        guard = InstallTreeGuard.capture()
        launch(...)
        diff = guard.recheck()
        if diff.host_replaced: rebind()
    """

    before: InstallTreeSnapshot
    root: str = ""
    platform: str | None = None

    @classmethod
    def capture(
        cls, *, root: Path | str | None = None, platform: str | None = None
    ) -> "InstallTreeGuard":
        snapshot = snapshot_install_tree(root, platform=platform)
        return cls(before=snapshot, root=snapshot.root, platform=platform)

    def recheck(self) -> InstallTreeDiff:
        """Re-snapshot the same root and diff it against the pre-launch state."""
        after = snapshot_install_tree(self.root or None, platform=self.platform)
        return diff_install_tree(self.before, after)


def known_builds(
    *, platform: str | None = None, edition: str | None = None
) -> tuple[HostVersion, ...]:
    """Every build the matrix lists for one platform/edition, verified first."""
    from ..hosts.versions import versions_for

    return versions_for(platform or get_provider().name, edition)


def describe(matrix: Iterable[HostVersion]) -> list[str]:
    """Render matrix entries for receipts; a receipt should be readable."""
    return [f"{entry.label} (Qt {entry.qt_version})" for entry in matrix]


__all__ = [
    "MAX_FILES",
    "MAX_TOTAL_BYTES",
    "NO_HOST",
    "PINNED",
    "UNPINNED",
    "UNSUPPORTED_PLATFORM",
    "InstallTreeDiff",
    "InstallTreeGuard",
    "InstallTreeSnapshot",
    "VersionGuard",
    "describe",
    "diff_install_tree",
    "guard_host_version",
    "install_root",
    "known_builds",
    "snapshot_install_tree",
]
