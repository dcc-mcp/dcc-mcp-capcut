"""Render the portable CapCut vlog recipe with the local FFmpeg fallback.

This is intentionally deterministic and does not require CapCut to be
installed. The resulting MP4 and receipt can be imported/verified in CapCut
when the host becomes available.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
OUTPUT = ROOT / "output" / "free-travel-vlog.mp4"
MUSIC = ASSETS / "free_ambient.wav"
RECEIPT = ROOT / "output" / "free-travel-vlog.receipt.json"


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def _duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def render() -> dict:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("ffmpeg and ffprobe are required to render the offline demo")
    earthrise = ASSETS / "earthrise.mp4"
    oahu = ASSETS / "oahu_flyover.mp4"
    if not earthrise.is_file() or not oahu.is_file():
        raise FileNotFoundError("download demo/assets/earthrise.mp4 and oahu_flyover.mp4 first")
    ASSETS.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if not MUSIC.is_file():
        run(
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:duration=12.2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=277.18:duration=12.2",
            "-filter_complex",
            "[0:a][1:a]amix=inputs=2,volume=0.08,afade=t=in:st=0:d=0.8,afade=t=out:st=11:d=1.2",
            "-ar",
            "48000",
            str(MUSIC),
        )
    # Microsoft YaHei is available on the target Windows desktop and gives
    # Chinese captions predictable glyph coverage. Keep Arial as a portable
    # fallback for non-Windows renderers.
    fontfile = Path("C:/Windows/Fonts/msyh.ttc")
    if not fontfile.is_file():
        fontfile = Path("C:/Windows/Fonts/arial.ttf")
    escaped_fontfile = fontfile.as_posix().replace(":", "\\:")
    font_option = f"fontfile='{escaped_fontfile}':" if fontfile.is_file() else ""
    vf = (
        "[0:v]trim=duration=4.5,setpts=PTS-STARTPTS,"
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"drawtext={font_option}text='抬头看，银河系就在我们身边':fontcolor=white:fontsize=48:"
        "box=1:boxcolor=black@0.45:boxborderw=22:x=(w-text_w)/2:y=h-360:"
        "enable='between(t,0.6,2.3)',"
        f"drawtext={font_option}text='这束光，可能已经走了数万年':fontcolor=FFE08A:fontsize=44:"
        "box=1:boxcolor=black@0.45:boxborderw=22:x=(w-text_w)/2:y=h-220:"
        "enable='between(t,2.4,4.3)'[v0];"
        "[1:v]trim=duration=8,setpts=PTS-STARTPTS,"
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"drawtext={font_option}text='太阳位于银河系的猎户臂':fontcolor=white:fontsize=48:"
        "box=1:boxcolor=black@0.45:boxborderw=22:x=(w-text_w)/2:y=h-360:"
        "enable='between(t,0.5,2.8)',"
        f"drawtext={font_option}text='银河系直径约 10 万光年':fontcolor=FFE08A:fontsize=48:"
        "box=1:boxcolor=black@0.45:boxborderw=22:x=(w-text_w)/2:y=h-220:"
        "enable='between(t,3.0,5.5)',"
        f"drawtext={font_option}text='我们不是旁观者，而是其中一颗星':fontcolor=white:fontsize=44:"
        "box=1:boxcolor=black@0.45:boxborderw=22:x=(w-text_w)/2:y=h-220:"
        "enable='between(t,5.7,7.8)'[v1];"
        "[v0][v1]concat=n=2:v=1:a=0[v]"
    )
    run(
        "ffmpeg",
        "-y",
        "-i",
        str(earthrise),
        "-i",
        str(oahu),
        "-i",
        str(MUSIC),
        "-filter_complex",
        vf,
        "-map",
        "[v]",
        "-map",
        "2:a",
        "-t",
        "12.5",
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(OUTPUT),
    )
    receipt = {
        "recipe": "demo/vlog_recipe.json",
        "output": str(OUTPUT.relative_to(ROOT.parent)).replace("\\", "/"),
        "sha256": hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
        "duration_seconds": round(_duration(OUTPUT), 3),
        "resolution": "1080x1920",
        "license": "NASA/JPL public-domain visuals; self-generated ambient audio",
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    print(json.dumps(render(), indent=2))
