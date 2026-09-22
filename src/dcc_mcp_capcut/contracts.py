"""Fail-closed result contracts for CapCut host mutations."""

from __future__ import annotations

from typing import Any

_MUTATING_ACTIONS = {
    "add_audio",
    "add_audio_fade",
    "add_clip",
    "add_text",
    "add_transition",
    "apply_edit_plan",
    "apply_effect",
    "auto_captions",
    "build_vlog_demo",
    "cancel_export",
    "close_project",
    "color_adjust",
    "configure_environment",
    "create_project",
    "create_timeline",
    "delete_clip",
    "export_thumbnail",
    "export_video",
    "generate_proxy",
    "import_media",
    "import_subtitles",
    "move_clip",
    "relink_media",
    "remove_audio",
    "remove_background",
    "remove_effect",
    "remove_media",
    "remove_text",
    "save_project",
    "set_audio_volume",
    "set_project_settings",
    "split_clip",
    "stabilize_clip",
    "trim_clip",
    "update_text",
}

_REQUIRED_IDS = {
    "add_audio": ("audio_id",),
    "apply_edit_plan": ("timeline_id",),
    "add_clip": ("clip_id",),
    "add_text": ("text_id",),
    "add_transition": ("transition_id",),
    "apply_effect": ("effect_id",),
    "auto_captions": ("caption_ids", "job_id"),
    "create_project": ("project_id",),
    "create_timeline": ("timeline_id",),
    "export_thumbnail": ("job_id", "output_path"),
    "export_video": ("job_id", "output_path"),
    "generate_proxy": ("job_id", "proxy_id"),
    "import_media": ("media_id",),
    "import_subtitles": ("caption_ids",),
    "remove_background": ("job_id", "clip_id"),
    "stabilize_clip": ("job_id", "clip_id"),
}

_TIMELINE_READBACK_ACTIONS = {
    "add_audio",
    "add_audio_fade",
    "add_clip",
    "add_text",
    "add_transition",
    "apply_edit_plan",
    "apply_effect",
    "auto_captions",
    "color_adjust",
    "delete_clip",
    "import_subtitles",
    "move_clip",
    "remove_audio",
    "remove_effect",
    "remove_text",
    "set_audio_volume",
    "split_clip",
    "trim_clip",
    "update_text",
}


def _has_value(result: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(result.get(key) not in (None, "", []) for key in keys)


def validate_host_result(action: str, result: Any) -> dict[str, Any]:
    """Require authoritative receipts before a mutation can report success."""
    if not isinstance(result, dict):
        raise RuntimeError(f"CapCut action '{action}' returned a non-object result")
    if action not in _MUTATING_ACTIONS:
        return result

    verification = result.get("verification")
    if not isinstance(verification, dict) or verification.get("ok") is not True:
        raise RuntimeError(f"CapCut action '{action}' lacks verified post-operation readback")

    required_ids = _REQUIRED_IDS.get(action)
    if required_ids and not _has_value(result, required_ids):
        expected = " or ".join(required_ids)
        raise RuntimeError(f"CapCut action '{action}' did not return {expected}")

    if action in _TIMELINE_READBACK_ACTIONS:
        timeline = verification.get("timeline")
        if not isinstance(timeline, dict):
            raise RuntimeError(f"CapCut action '{action}' lacks timeline readback")

    return result
