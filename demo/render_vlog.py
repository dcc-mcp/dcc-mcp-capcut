"""Render the portable CapCut vlog recipe with the local FFmpeg fallback.

The render is driven by the canonical edit plan
(``dcc-mcp-capcut/edit-plan/v1``), the same document ``apply_edit_plan``
assembles into CapCut and ``export_otio`` lowers to OTIO. Compiling first means
this offline proof, the OTIO delivery and the native assembly all reject the
same plan for the same reason; the compiled plan is written next to the render
so the same file can be replayed through the host.

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

from dcc_mcp_capcut.editplan import compile_plan, plan_to_actions

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
OUTPUT = ROOT / "output" / "free-travel-vlog.mp4"
PLAN = ROOT / "output" / "free-travel-vlog.plan.json"
MUSIC = ASSETS / "free_ambient.wav"
RECEIPT = ROOT / "output" / "free-travel-vlog.receipt.json"

DEFAULT_FONT_SIZE = 48
# Caption lanes inside a 1080x1920 frame: the first caption in a clip sits
# higher, later ones stack below it.
CAPTION_LANES = (360, 220)


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


def _escape_drawtext(text: str) -> str:
    """Escape the characters FFmpeg's drawtext parser expands."""
    for character in ("\\", "'", ":", "%"):
        text = text.replace(character, "\\" + character)
    return text


def _font_color(style: dict) -> str:
    color = str(style.get("color", "#FFFFFF")).lstrip("#")
    return "white" if color.upper() == "FFFFFF" else color


def media_index() -> dict[str, str]:
    """Map asset ids to their local relative paths, as recorded in assets.json."""
    assets = json.loads((ROOT / "assets.json").read_text(encoding="utf-8"))
    return {asset["id"]: asset["local_path"] for asset in assets["assets"]}


def picture_clips(plan: dict) -> list[dict]:
    """The base picture track's clips in timeline order."""
    for track in plan["tracks"]:
        if track["kind"] == "Video":
            return sorted(track["clips"], key=lambda clip: clip["start"])
    return []


def music_clip(plan: dict) -> dict | None:
    """The single music-bed clip the offline renderer supports."""
    for track in plan["tracks"]:
        if track["kind"] == "Audio":
            return track["clips"][0] if track["clips"] else None
    return None


def duration_seconds(plan: dict) -> float:
    return round(plan["duration_frames"] / plan["fps"], 3)


def build_filter(plan: dict, font_option: str = "") -> str:
    """Build the FFmpeg filter graph from the canonical plan.

    Only straight cuts are representable here: the picture clips are trimmed,
    scaled and concatenated, and each caption is drawn onto the clip that covers
    it, at clip-local times. A caption that spans a cut is clamped to the end of
    the clip it starts in -- offline rendering cannot place overlay tracks, so a
    genuinely overlapping plan belongs in CapCut (``apply_edit_plan``), not here.
    """
    width, height = plan["width"], plan["height"]
    fps = plan["fps"]
    clips = picture_clips(plan)
    chains = []

    for index, clip in enumerate(clips):
        start = clip["start"] / fps
        end = (clip["start"] + clip["duration"]) / fps
        parts = [
            f"[{index}:v]trim=duration={round(clip['duration'] / fps, 3)},setpts=PTS-STARTPTS,",
            f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
        ]
        captions = [
            caption for caption in plan["captions"] if start <= caption["start"] / fps < end
        ]
        for lane, caption in enumerate(captions):
            style = caption.get("style") or {}
            local_start = max(0.0, round(caption["start"] / fps - start, 3))
            local_end = min(
                round(end - start, 3),
                round((caption["start"] + caption["duration"]) / fps - start, 3),
            )
            lane_offset = CAPTION_LANES[min(lane, len(CAPTION_LANES) - 1)]
            parts.append(
                f",drawtext={font_option}text='{_escape_drawtext(caption['text'])}':"
                f"fontcolor={_font_color(style)}:fontsize={style.get('size', DEFAULT_FONT_SIZE)}:"
                f"box=1:boxcolor=black@0.45:boxborderw=22:x=(w-text_w)/2:y=h-{lane_offset}:"
                f"enable='between(t,{local_start},{local_end})'"
            )
        parts.append(f"[v{index}]")
        chains.append("".join(parts))

    if not chains:
        raise ValueError("the plan places no picture clip; nothing to render")
    labels = "".join(f"[v{index}]" for index in range(len(chains)))
    chains.append(f"{labels}concat=n={len(chains)}:v=1:a=0[v]")
    return ";".join(chains)


def render() -> dict:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("ffmpeg and ffprobe are required to render the offline demo")

    recipe = json.loads((ROOT / "vlog_recipe.json").read_text(encoding="utf-8"))
    plan = compile_plan(recipe, media_index=media_index())
    total = duration_seconds(plan)

    clips = picture_clips(plan)
    if not clips:
        raise ValueError("the plan places no picture clip; nothing to render")
    sources = [ASSETS / Path(clip["media"]).name for clip in clips]
    missing = [str(source) for source in sources if not source.is_file()]
    if missing:
        raise FileNotFoundError("download the demo assets first: " + ", ".join(missing))

    ASSETS.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    music = music_clip(plan)
    mix = (music or {}).get("audio") or {}
    volume = mix.get("volume", 0.08)
    fade_in = mix.get("fade_in", 0.0)
    fade_out = mix.get("fade_out", 0.0)

    if not MUSIC.is_file():
        audio_filter = f"amix=inputs=2,volume={volume}"
        if fade_in:
            audio_filter += f",afade=t=in:st=0:d={fade_in}"
        if fade_out:
            audio_filter += f",afade=t=out:st={round(total - fade_out, 3)}:d={fade_out}"
        run(
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=220:duration={total}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=277.18:duration={total}",
            "-filter_complex",
            audio_filter,
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

    vf = build_filter(plan, font_option=font_option)
    music_index = len(sources)
    run(
        "ffmpeg",
        "-y",
        *[argument for source in sources for argument in ("-i", str(source))],
        "-i",
        str(MUSIC),
        "-filter_complex",
        vf,
        "-map",
        "[v]",
        "-map",
        f"{music_index}:a",
        "-t",
        str(total),
        "-r",
        str(plan["fps"]),
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
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "recipe": "demo/vlog_recipe.json",
        "plan": str(PLAN.relative_to(ROOT.parent)).replace("\\", "/"),
        "plan_schema": plan["schema"],
        "output": str(OUTPUT.relative_to(ROOT.parent)).replace("\\", "/"),
        "sha256": hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
        "duration_seconds": round(_duration(OUTPUT), 3),
        "resolution": f"{plan['width']}x{plan['height']}",
        "assembly_steps": len(plan_to_actions(plan)["actions"]),
        "license": "NASA/JPL public-domain visuals; self-generated ambient audio",
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    print(json.dumps(render(), indent=2))
