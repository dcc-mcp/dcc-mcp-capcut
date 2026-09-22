"""Build a deterministic CapCut panel release archive.

The archive ships a ``manifest.json`` that records a SHA-256 for every payload
member, so a consumer can verify the artifact rather than trust it:

    python tools/build_panel_archive.py --verify <archive.zip>

``host_acceptance`` is optional host-build evidence (architecture, compiler ABI,
Qt version, probe protocol, and the acceptance run that backs them). The shared
Python panel build neither needs nor fabricates it; a future native bundle from
``native/qt-probe`` should reuse this same manifest shape and supply it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

FILES = ("HOST_API.md", "index.html", "panel.js")
PANEL_PREFIX = "panel"
MANIFEST_NAME = "manifest.json"
TIMESTAMP = (2020, 1, 1, 0, 0, 0)


def sha256_hex(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def write_file(archive: ZipFile, name: str, data: bytes) -> None:
    info = ZipInfo(name, TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


def panel_payloads(panel: Path) -> dict[str, bytes]:
    """Read the bundled panel files, keyed by their archive member name."""
    return {f"{PANEL_PREFIX}/{name}": (panel / name).read_bytes() for name in FILES}


def build_manifest(
    version: str,
    payloads: Mapping[str, bytes],
    host_acceptance: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Assemble the archive manifest.

    Digests are keyed by archive member name, so verification is a straight
    lookup after extraction. ``host_acceptance`` is omitted entirely when it is
    not supplied: the field is optional and old consumers must keep working.
    """
    manifest: dict[str, object] = {
        "adapter": "capcut",
        "version": version,
        "files": list(FILES),
        "files_sha256": {name: sha256_hex(data) for name, data in sorted(payloads.items())},
    }
    if host_acceptance is not None:
        manifest["host_acceptance"] = dict(host_acceptance)
    return manifest


def build(
    output: Path,
    version: str,
    host_acceptance: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Write the panel archive to ``output`` and return the manifest it records."""
    panel = Path(__file__).parents[1] / "src" / "dcc_mcp_capcut" / "capcut_panel"
    payloads = panel_payloads(panel)
    manifest = build_manifest(version, payloads, host_acceptance)
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w") as archive:
        write_file(
            archive,
            MANIFEST_NAME,
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode(),
        )
        for name, data in payloads.items():
            write_file(archive, name, data)
    return manifest


def verify_archive(path: Path) -> list[str]:
    """Check ``path`` against its own manifest.

    Returns a list of human-readable problems; an empty list means every member
    is present, covered by the manifest, and matches its recorded digest.
    """
    with ZipFile(path) as archive:
        members = set(archive.namelist())
        if MANIFEST_NAME not in members:
            return [f"{MANIFEST_NAME} is missing from the archive"]
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME))
        except (ValueError, UnicodeDecodeError) as error:
            return [f"{MANIFEST_NAME} is not readable JSON: {error}"]
        if not isinstance(manifest, dict):
            return [f"{MANIFEST_NAME} is not a JSON object"]

        problems: list[str] = []
        recorded = manifest.get("files_sha256")
        if not isinstance(recorded, dict) or not recorded:
            return [f"{MANIFEST_NAME} records no files_sha256 digests"]

        for name, digest in sorted(recorded.items()):
            if name not in members:
                problems.append(f"{name} is recorded in the manifest but missing from the archive")
                continue
            actual = sha256_hex(archive.read(name))
            if actual != digest:
                problems.append(f"{name} digest mismatch: expected {digest}, got {actual}")

        for name in sorted(members - set(recorded) - {MANIFEST_NAME}):
            problems.append(f"{name} is in the archive but has no recorded digest")

        declared = manifest.get("files")
        if isinstance(declared, list):
            for name in declared:
                if f"{PANEL_PREFIX}/{name}" not in recorded:
                    problems.append(f"{PANEL_PREFIX}/{name} is listed in 'files' but has no digest")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or verify a CapCut panel release archive.")
    parser.add_argument("--output", type=Path, help="archive to write")
    parser.add_argument("--version", help="adapter version recorded in the manifest")
    parser.add_argument(
        "--host-acceptance",
        type=Path,
        help="JSON file with optional host-build acceptance evidence to embed",
    )
    parser.add_argument(
        "--verify",
        type=Path,
        help="verify an existing archive against its manifest instead of building one",
    )
    args = parser.parse_args(argv)

    if args.verify is not None:
        problems = verify_archive(args.verify)
        for problem in problems:
            print(f"{args.verify}: {problem}", file=sys.stderr)
        if problems:
            return 1
        print(f"{args.verify}: ok")
        return 0

    if not args.output or not args.version:
        parser.error("--output and --version are required unless --verify is used")

    host_acceptance = None
    if args.host_acceptance is not None:
        host_acceptance = json.loads(args.host_acceptance.read_text(encoding="utf-8"))
        if not isinstance(host_acceptance, dict):
            parser.error("--host-acceptance must contain a JSON object")

    build(args.output, args.version, host_acceptance)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
