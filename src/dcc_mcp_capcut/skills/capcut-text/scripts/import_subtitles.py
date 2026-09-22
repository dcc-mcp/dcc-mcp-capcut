"""Import one subtitle file as an editable CapCut text track.

``align`` decides how the file's timecodes map onto the timeline, and it is
resolved in the adapter before anything is dispatched:

``timecode`` (default)
    Hand the file to the host exactly as it is and let its own clock stand.
    Nothing is read or written here -- byte-for-byte the previous behaviour.

``sequence``
    Parse the file offline, discard the absolute timecodes, pack the cues back
    to back from ``offset``, write the result as SRT and import that. The host
    only ever sees a plain SRT file at a plain path, so the strategy means the
    same thing on every host build instead of depending on one that happens to
    implement an ``align`` parameter.

``align`` and ``output_path`` are stripped before dispatch in both cases: they
are instructions to this adapter, not host parameters, and forwarding them
would either be rejected by a strict host or silently ignored by a permissive
one -- which is precisely how "the alignment never happened" goes unnoticed.
"""

from __future__ import annotations

from typing import Any

from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.bridge import call_bridge
from dcc_mcp_capcut.contracts import validate_host_result
from dcc_mcp_capcut.subtitles import prepare_import_params


@skill_entry
def main(
    path: str,
    timeline_id: str = None,
    format: str = None,
    offset: float = 0.0,
    language: str = None,
    style: dict = None,
    align: str = "timecode",
    output_path: str = None,
):
    # Build the request from what was actually supplied: `offset` defaults to
    # 0.0 and is always meaningful, the rest are absent unless asked for. A
    # null reaching the host is not the same thing as an omitted key.
    supplied = {
        "path": str(path),
        "timeline_id": timeline_id,
        "format": format,
        "offset": offset,
        "language": language,
        "style": style,
        "align": align,
        "output_path": output_path,
    }
    requested = {key: value for key, value in supplied.items() if value is not None}

    dispatched = prepare_import_params(requested)
    result = validate_host_result("import_subtitles", call_bridge("import_subtitles", dispatched))
    payload: dict[str, Any] = {
        "action": "import_subtitles",
        "align": requested.get("align") or "timecode",
        "imported_path": dispatched["path"],
        **result,
    }
    if "output_path" in requested:
        payload["output_path"] = requested["output_path"]
    return skill_success(f"CapCut imported subtitles from {dispatched['path']}.", **payload)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
