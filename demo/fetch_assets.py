"""Fetch the public-domain visual inputs listed in assets.json."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent


def fetch() -> None:
    catalog = json.loads((ROOT / "assets.json").read_text(encoding="utf-8"))
    target = ROOT / "assets"
    target.mkdir(parents=True, exist_ok=True)
    for asset in catalog["assets"]:
        url = asset.get("download_url")
        if not url:
            continue
        name = url.rsplit("/", 1)[-1]
        path = target / name
        if path.is_file() and path.stat().st_size > 1024:
            print(f"exists {path}")
            continue
        print(f"download {url}")
        with urlopen(url, timeout=60) as response:  # noqa: S310 - catalog-controlled HTTPS
            path.write_bytes(response.read())

    earthrise = target / "fromearth2_360p30.mp4"
    if earthrise.exists() and not (target / "earthrise.mp4").exists():
        earthrise.replace(target / "earthrise.mp4")
    oahu = target / "PIA14898_ASTER_Oahu_320.mp4"
    if oahu.exists() and not (target / "oahu_flyover.mp4").exists():
        oahu.replace(target / "oahu_flyover.mp4")


if __name__ == "__main__":
    fetch()
