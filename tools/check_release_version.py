"""Refuse to publish a release whose artifacts do not agree on one version.

The wheel and sdist take their version from ``pyproject.toml``, while the panel
archive takes the one handed to ``tools/build_panel_archive.py --version`` --
``RELEASE_TAG`` in ``release.yml``. Nothing checked that the two chains agreed,
so a tree whose ``pyproject.toml`` lagged behind the tag shipped a single
release mixing ``dcc_mcp_capcut-0.1.0-*.whl`` with
``dcc-mcp-capcut-0.2.0-panel.zip``.

This module is that missing check. It reads the version back out of every
artifact that is about to be uploaded, so the gate judges what was actually
built rather than what the tree claims:

.. code-block:: bash

    python tools/check_release_version.py                       # sources only
    python tools/check_release_version.py --print-version        # the in-tree version
    python tools/check_release_version.py --expect 0.3.0 --dist dist

Without ``--expect`` the inputs are only required to agree with each other;
with it, every input must declare that exact version. A non-zero exit is the
signal. Problems are always written to stderr, and additionally emitted as a
GitHub error annotation when ``$GITHUB_ACTIONS`` is set, so a failed gate is
readable on the run page and ``--print-version`` keeps stdout to itself.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tarfile
from pathlib import Path
from typing import Callable
from zipfile import BadZipFile, ZipFile

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python < 3.11
    tomllib = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
VERSION_FILE = REPO_ROOT / "src" / "dcc_mcp_capcut" / "__version__.py"

PANEL_SUFFIX = "-panel.zip"
PANEL_MANIFEST = "manifest.json"
SDIST_SUFFIX = ".tar.gz"
WHEEL_SUFFIX = ".whl"
METADATA_SUFFIX = ".dist-info/METADATA"

# A parsed value that is not a version is a parse that went wrong somewhere,
# and reporting it as a mismatch would read like a bump request.
# The suffix has to carry something: `1.2.3-` is what a typo looks like, and no
# build backend would have produced it.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+].+)?$")
PACKAGE_VERSION_RE = re.compile(r"""^__version__\s*=\s*["']([^"']+)["']""", re.MULTILINE)
PROJECT_VERSION_RE = re.compile(r"""^version\s*=\s*["']([^"']+)["']""")


def label(path: Path) -> str:
    """Name ``path`` the way a reader of the run log would recognise it.

    Paths are reported with ``/`` even on Windows so that an annotation is
    identical whichever runner produced it.
    """
    try:
        relative = path.relative_to(Path.cwd())
    except ValueError:
        return path.name
    return relative.as_posix()


def project_version_without_tomllib(text: str) -> str | None:
    """Read ``[project].version`` by line scan, for Python without ``tomllib``.

    The scan follows table headers so that a ``version`` key belonging to some
    other table cannot be picked up as the project's: on Python 3.9, where this
    fallback is what runs, silently reading the wrong table would turn the gate
    into a no-op that compares an unrelated version to the tag.
    """
    in_project = False
    for raw in text.splitlines():
        line = raw.strip()
        # A header may carry a trailing comment, so `[project] # release
        # metadata` is still the header the scan has to recognise. Only a `#`
        # after the closing bracket can be a comment; one inside the brackets
        # belongs to a quoted key such as `["a#b"]`.
        closing = line.find("]") if line.startswith("[") else -1
        if closing != -1 and "#" in line[closing:]:
            line = line[: closing + 1]
        if line.startswith("[") and line.endswith("]"):
            in_project = line == "[project]"
            continue
        if in_project:
            match = PROJECT_VERSION_RE.match(line)
            if match is not None:
                return match.group(1)
    return None


def read_project_version(path: Path) -> str:
    """Return the version declared by ``[project].version`` in a PEP 621 file."""
    text = path.read_text(encoding="utf-8")
    version = (
        tomllib.loads(text).get("project", {}).get("version")
        if tomllib is not None
        else project_version_without_tomllib(text)
    )
    if not isinstance(version, str) or not version:
        raise ValueError(f"{path.name} declares no [project].version to build from")
    return version


def read_package_version(path: Path) -> str:
    """Return ``__version__`` as the module assigns it, without importing it.

    Importing the package would pull in ``dcc_mcp_core`` and answer a question
    about installed dependencies instead of the file this release ships.
    """
    match = PACKAGE_VERSION_RE.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"{path.name} assigns no __version__")
    return match.group(1)


def metadata_field_version(text: str, field: str, source: str) -> str:
    """Return a core-metadata header value, stopping at the end of the headers."""
    needle = field.lower()
    for line in text.splitlines():
        if not line.strip():
            break
        if line.lower().startswith(needle):
            value = line.split(":", 1)[1].strip()
            if value:
                return value
    raise ValueError(f"{source} has no {field} header")


def wheel_filename_version(path: Path) -> str:
    """Return the version component of a PEP 427 wheel filename.

    Escaping makes ``-`` unambiguous in a wheel name, so the version is always
    the second component. Requiring five components rejects a truncated or
    hand-made name that would otherwise parse into something version-shaped.
    """
    parts = path.stem.split("-")
    if len(parts) < 5:
        raise ValueError(f"{path.name} is not a PEP 427 wheel filename")
    return parts[1]


def sdist_filename_version(path: Path) -> str:
    """Return the version component of an sdist filename."""
    name = path.name
    if not name.endswith(SDIST_SUFFIX) or name == SDIST_SUFFIX.lstrip("."):
        raise ValueError(f"{path.name} is not an sdist filename")
    stem = name[: -len(SDIST_SUFFIX)]
    if "-" not in stem:
        raise ValueError(f"{path.name} is not an sdist filename")
    return stem.rsplit("-", 1)[1]


def panel_filename_version(path: Path) -> str:
    """Return the version component of a panel archive filename."""
    stem = path.name[: -len(".zip")] if path.name.endswith(".zip") else path.name
    if not stem.endswith("-panel"):
        raise ValueError(f"{path.name} is not a panel archive filename")
    stem = stem[: -len("-panel")]
    if "-" not in stem:
        raise ValueError(f"{path.name} is not a panel archive filename")
    return stem.rsplit("-", 1)[1]


def wheel_version(path: Path) -> str:
    """Return the version a wheel declares, cross-checked against its filename.

    ``METADATA`` is what an installer reads, but consumers see the filename, so
    a release where the two disagree is broken whichever one is right.
    """
    with ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(METADATA_SUFFIX)]
        if len(names) != 1:
            raise ValueError(
                f"{path.name} holds {len(names)} {METADATA_SUFFIX} members, expected exactly 1"
            )
        text = archive.read(names[0]).decode("utf-8", errors="replace")
    version = metadata_field_version(text, "Version:", path.name)
    declared = wheel_filename_version(path)
    if declared != version:
        raise ValueError(f"{path.name} names {declared!r} but its METADATA says {version!r}")
    return version


def sdist_version(path: Path) -> str:
    """Return the version an sdist declares, cross-checked against its filename."""
    with tarfile.open(path, "r:gz") as archive:
        members = [
            member
            for member in archive.getmembers()
            if member.isfile() and Path(member.name).name == "PKG-INFO"
        ]
        if not members:
            raise ValueError(f"{path.name} contains no PKG-INFO")
        member = min(members, key=lambda candidate: candidate.name.count("/"))
        extracted = archive.extractfile(member)
        if extracted is None:
            raise ValueError(f"{path.name}: PKG-INFO cannot be extracted")
        text = extracted.read().decode("utf-8", errors="replace")
    version = metadata_field_version(text, "Version:", path.name)
    declared = sdist_filename_version(path)
    if declared != version:
        raise ValueError(f"{path.name} names {declared!r} but its PKG-INFO says {version!r}")
    return version


def panel_version(path: Path) -> str:
    """Return the version a panel archive records, cross-checked against its name.

    The manifest is what ``build_panel_archive.py --verify`` and downstream
    consumers read, so it is the authoritative half here.
    """
    with ZipFile(path) as archive:
        try:
            raw = archive.read(PANEL_MANIFEST)
        except KeyError as error:
            raise ValueError(f"{path.name} contains no {PANEL_MANIFEST}") from error
        try:
            manifest = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise ValueError(
                f"{path.name}: {PANEL_MANIFEST} is not readable JSON: {error}"
            ) from error
    version = manifest.get("version") if isinstance(manifest, dict) else None
    if not isinstance(version, str) or not version:
        raise ValueError(f"{path.name}: {PANEL_MANIFEST} records no version")
    declared = panel_filename_version(path)
    if declared != version:
        raise ValueError(f"{path.name} names {declared!r} but its manifest says {version!r}")
    return version


def artifact_reader(path: Path) -> Callable[[Path], str] | None:
    """Return the reader for a known artifact kind, or ``None`` for anything else."""
    name = path.name
    if name.endswith(WHEEL_SUFFIX):
        return wheel_version
    if name.endswith(SDIST_SUFFIX):
        return sdist_version
    if name.endswith(PANEL_SUFFIX):
        return panel_version
    return None


def check(
    dist: Path | None = None,
    expect: str | None = None,
    *,
    pyproject: Path = PYPROJECT,
    version_file: Path = VERSION_FILE,
) -> tuple[dict[str, str], list[str]]:
    """Collect every declared version and report the ways they fail the gate.

    Returns ``(versions, problems)``. A file that cannot be read at all appears
    only in ``problems``: recording a version for it would let a missing
    artifact be counted as an agreed one.
    """
    versions: dict[str, str] = {}
    problems: list[str] = []

    for path, reader in (
        (pyproject, read_project_version),
        (version_file, read_package_version),
    ):
        try:
            versions[label(path)] = reader(path)
        except (OSError, ValueError) as error:
            problems.append(f"{label(path)}: {error}")

    if dist is not None:
        dist = Path(dist)
        if not dist.is_dir():
            problems.append(f"{label(dist)}: not a directory of built artifacts")
            return versions, problems
        artifacts = sorted(path for path in dist.iterdir() if path.is_file())
        if not artifacts:
            problems.append(f"{label(dist)}: no artifacts found to check")
        for artifact in artifacts:
            reader = artifact_reader(artifact)
            if reader is None:
                # Fail closed: an unrecognised file is still about to be
                # uploaded, and a gate that ignores what it cannot read is
                # silent exactly where the version is unknown.
                problems.append(f"{label(artifact)}: not a versioned release artifact")
                continue
            try:
                versions[label(artifact)] = reader(artifact)
            except (OSError, ValueError, BadZipFile, tarfile.TarError) as error:
                problems.append(f"{label(artifact)}: {error}")

    malformed = set()
    for name, version in sorted(versions.items()):
        if not VERSION_RE.match(version):
            malformed.add(name)
            problems.append(f"{name}: {version!r} is not a version")

    if expect is not None:
        for name, version in sorted(versions.items()):
            if name in malformed:
                # Already reported: comparing a non-version to the expected one
                # would add a second line that reads like a bump request.
                continue
            if version != expect:
                problems.append(f"{name}: declares {version!r}, not the release version {expect!r}")
    elif len(set(versions.values())) > 1:
        # Without an expected version, agreement is the only thing being gated.
        disagreeing = "; ".join(f"{name}={version!r}" for name, version in sorted(versions.items()))
        problems.append(f"artifacts disagree on the version: {disagreeing}")

    return versions, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when the release artifacts do not agree on one version."
    )
    parser.add_argument("--dist", type=Path, help="directory of built artifacts to check")
    parser.add_argument(
        "--expect",
        help="version every input must declare (the release tag without its leading v)",
    )
    parser.add_argument(
        "--print-version",
        action="store_true",
        dest="print_version",
        help="print the version the sources declare, after checking they agree",
    )
    parser.add_argument("--pyproject", type=Path, default=PYPROJECT)
    parser.add_argument("--version-file", type=Path, default=VERSION_FILE)
    args = parser.parse_args(argv)

    versions, problems = check(
        args.dist,
        args.expect,
        pyproject=args.pyproject,
        version_file=args.version_file,
    )

    if args.print_version:
        source = label(args.pyproject)
        if not problems and source in versions:
            print(versions[source])

    for problem in problems:
        # Annotations go to stderr so stdout stays clean for --print-version,
        # whose output is captured into $GITHUB_OUTPUT by the workflows.
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::error::{problem}", file=sys.stderr)
        else:
            print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
