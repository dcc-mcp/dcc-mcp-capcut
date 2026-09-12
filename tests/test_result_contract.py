import pytest

from dcc_mcp_capcut.contracts import validate_host_result


def test_mutation_rejects_bare_acceptance():
    with pytest.raises(RuntimeError, match="verified post-operation readback"):
        validate_host_result("import_media", {"accepted": True})


def test_import_subtitles_requires_timeline_readback():
    with pytest.raises(RuntimeError, match="timeline readback"):
        validate_host_result(
            "import_subtitles",
            {
                "caption_ids": ["caption-1"],
                "verification": {"ok": True},
            },
        )


def test_import_subtitles_accepts_verified_editable_track():
    result = {
        "caption_ids": ["caption-1", "caption-2"],
        "verification": {
            "ok": True,
            "timeline": {"text_track_count": 1, "caption_count": 2},
        },
    }

    assert validate_host_result("import_subtitles", result) is result


def test_read_only_result_does_not_require_mutation_receipt():
    result = {"project": {"name": "demo"}}
    assert validate_host_result("inspect_project", result) is result
