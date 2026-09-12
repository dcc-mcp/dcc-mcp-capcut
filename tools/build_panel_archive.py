"""Build a deterministic CapCut panel release archive."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

FILES = ("HOST_API.md", "index.html", "panel.js")
TIMESTAMP = (2020, 1, 1, 0, 0, 0)


def write_file(archive: ZipFile, name: str, data: bytes) -> None:
    info = ZipInfo(name, TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


def build(output: Path, version: str) -> None:
    panel = Path(__file__).parents[1] / "src" / "dcc_mcp_capcut" / "capcut_panel"
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w") as archive:
        write_file(
            archive,
            "manifest.json",
            json.dumps(
                {"adapter": "capcut", "version": version, "files": list(FILES)},
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
        )
        for name in FILES:
            write_file(archive, f"panel/{name}", (panel / name).read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    build(args.output, args.version)


if __name__ == "__main__":
    main()
