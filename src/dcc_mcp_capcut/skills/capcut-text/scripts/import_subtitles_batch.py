"""Import several subtitle files in one call -- one editable text track each.

The multi-language case is the reason this exists: a zh-CN and an en-US SRT for
the same cut is two imports, and doing them as two tool calls leaves the
timeline half-populated whenever the second one fails. This walks the list and
reports exactly what landed, in the same fail-closed shape the assembly walk
uses.

One file per ``import_subtitles`` call, because the contract returns a single
``caption_ids`` list per call and a merged import could not be mapped back to
the language it came from.

The host is **not** rolled back on a part-way failure. That is stated rather
than worked around: undoing an import would mean deleting caption items by id,
and guessing which ones this call created is how an unrelated track gets
destroyed.
"""

from __future__ import annotations

from typing import Any

from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.bridge import call_bridge
from dcc_mcp_capcut.contracts import validate_host_result
from dcc_mcp_capcut.subtitles import prepare_import_params

#: Keys a batch item accepts. `timeline_id` is deliberately absent -- it is a
#: property of the call, not of one item, and letting each item name a
#: different timeline would make "one call, one timeline" untrue.
ITEM_KEYS = ("path", "format", "offset", "language", "style", "align", "output_path")


def _validate_item(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError(f"items[{index}] must be an object")
    unknown = sorted(set(item) - set(ITEM_KEYS))
    if unknown:
        raise ValueError(f"items[{index}] has unsupported fields: {unknown}")
    path = item.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ValueError(f"items[{index}] requires a non-empty 'path'")
    return {key: value for key, value in item.items() if value is not None}


@skill_entry
def main(items: list, timeline_id: str = None):
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty list of subtitle requests")

    # Validate every item before the first dispatch. Checking lazily would let
    # item 3 being malformed surface only after items 1 and 2 were already
    # imported -- and since the host is not rolled back, the caller would be
    # left with a half-populated timeline and an error about a file it never
    # got to. The whole point of a batch call is that it is one unit of work.
    requests = []
    for index, entry in enumerate(items):
        request = _validate_item(entry, index)
        if timeline_id is not None:
            request["timeline_id"] = timeline_id
        requests.append(request)

    imported: list[dict[str, Any]] = []
    caption_ids: list[str] = []
    timeline_readback: dict[str, Any] | None = None
    readback_from: str | None = None

    for index, request in enumerate(requests):
        dispatched = prepare_import_params(request)
        try:
            result = validate_host_result(
                "import_subtitles", call_bridge("import_subtitles", dispatched)
            )
        except (RuntimeError, OSError) as error:
            raise RuntimeError(
                f"import_subtitles_batch stopped at item {index} ({request['path']}): {error}. "
                f"Items already imported: {[done['path'] for done in imported] or ['none']}. "
                "The host is not rolled back -- inspect the project before retrying."
            ) from error

        ids = result.get("caption_ids") or []
        if isinstance(ids, list):
            caption_ids.extend(str(value) for value in ids)
        verification = result.get("verification")
        if isinstance(verification, dict) and isinstance(verification.get("timeline"), dict):
            timeline_readback = verification["timeline"]
            readback_from = result.get("timeline_id") or timeline_id
        imported.append(
            {
                "path": dispatched["path"],
                "language": request.get("language"),
                "align": request.get("align") or "timecode",
                "caption_ids": ids,
                "caption_count": len(ids) if isinstance(ids, list) else 0,
            }
        )

    return skill_success(
        f"CapCut imported {len(imported)} subtitle file(s) as separate text tracks.",
        action="import_subtitles_batch",
        imported=imported,
        caption_ids=caption_ids,
        caption_count=len(caption_ids),
        timeline_id=timeline_id,
        verification={
            "ok": True,
            "timeline": timeline_readback,
            "readback_from": readback_from,
            "steps": len(imported),
        },
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
