"""Transcribe media through the user's own ASR executor.

The adapter owns the seam, not the engine. It validates the request, runs
whatever executable ``DCC_MCP_CAPCUT_ASR_EXECUTOR`` names, and normalises the
result into segments, SRT text and -- when ``fps`` is supplied -- canonical plan
captions. Nothing here loads a model or downloads a weight, because which ASR
to use is the user's decision to make.

The failure a caller sees is specific enough to act on: unconfigured executor,
missing or non-executable file, timeout, unparseable output, or a non-zero exit
carrying the executor's own last stderr line.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut import asr
from dcc_mcp_capcut.editplan import cues_to_captions


@skill_entry
def main(
    media: str,
    language: str = None,
    output_format: str = "srt",
    timeout: float = None,
    output_path: str = None,
    fps: float = None,
    executor: str = None,
):
    if output_format not in asr.OUTPUT_FORMATS:
        raise ValueError(f"output_format must be one of {list(asr.OUTPUT_FORMATS)}")

    transcript = asr.transcribe(
        media,
        language=language,
        output_format=output_format,
        timeout=timeout,
        executor=executor,
    )

    payload: dict[str, Any] = {
        "action": "transcribe",
        "media": str(Path(str(media)).expanduser()),
        "executor": transcript.executor,
        "output_format": transcript.output_format,
        "language": transcript.language,
        "segment_count": len(transcript.segments),
        "segments": [
            {"start": segment.start, "end": segment.end, "text": segment.text}
            for segment in transcript.segments
        ],
        "duration": transcript.duration,
    }

    # Cues come from the normalised transcript itself, not from re-parsing the
    # rendered SRT: a segment with empty text renders a block with no text
    # line, which the parser rejects, so round-tripping would turn a successful
    # transcription into a parser error about output the caller never supplied.
    # Deriving both from one source also means they cannot disagree.
    payload["srt"] = transcript.srt
    if fps is not None:
        payload["captions"] = cues_to_captions(transcript.cues, fps)
        payload["fps"] = float(fps)

    if output_path:
        target = Path(str(output_path)).expanduser()
        if target.parent and not target.parent.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(transcript.srt, encoding="utf-8")
        payload["output_path"] = str(target)

    message = (
        f"Transcribed {len(transcript.segments)} segments "
        f"({transcript.duration:.2f}s) through the configured ASR executor."
    )
    return skill_success(message, prompt=None, **payload)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
