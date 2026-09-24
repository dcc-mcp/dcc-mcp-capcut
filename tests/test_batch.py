"""Batch production: one template plus N variable sets becomes N renders.

The host is not reachable from CI, so these tests pin what is provable
offline, and the split is deliberate:

* ``dcc_mcp_capcut.batch`` is host-free, so substitution, the reframe
  arithmetic, the encode preset, the manifest and the item state machine are
  all asserted directly, with no bridge anywhere near them.
* The three skill scripts are driven through a recording fake bridge, with the
  poll clock and the sleep injected, so a batch of several items runs to
  completion in microseconds and the assertions are about *dispatch* -- how
  many items were attempted, which ones were delivered, what survived a
  failure, and what a resume did with the manifest.

The properties that matter here are failure isolation and resumability: a
batch that renders twenty items and loses one must still deliver nineteen, and
one that is interrupted must not re-render what it already paid for.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from dcc_mcp_capcut import assemble as assemble_module
from dcc_mcp_capcut.batch import (
    BATCH_SCHEMA,
    begin_item,
    build_batch,
    complete_item,
    fail_item,
    fresh_overwrite_check,
    item_counts,
    load_batch,
    render_template,
    save_batch,
    select_items,
    skip_item,
    substitute_variables,
    summarize,
)
from dcc_mcp_capcut.editplan import compile_plan, plan_to_actions

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "src" / "dcc_mcp_capcut" / "skills" / "capcut-batch" / "scripts"

TIMELINE = {"tracks": 1, "duration": 4.0}

# A vlog recipe carrying every directive this module owns: a placeholder in a
# media path, in the project name and in the destination, a subtitled language
# variant, a reframing policy and an encode preset.
TEMPLATE = {
    "schema": "capcut-vlog-recipe/v1",
    "project_name": "promo {{lang}} {{aspect}}",
    "aspect_ratio": "{{aspect}}",
    "output_path": "out/promo_{{lang}}_{{aspect}}.mp4",
    "media": [{"id": "a", "path": "clips/{{lang}}/a.mp4", "start": 0, "duration": "{{length}}"}],
    "subtitle_files": ["subs/{{lang}}.srt"],
    "reframe": {"fit": "contain", "source_aspect_ratio": "16:9"},
    "export": {"codec": "h264", "bitrate_mbps": 12},
}

VARIABLES = [
    {"lang": "en", "aspect": "16:9", "length": 8},
    {"lang": "zh", "aspect": "9:16", "length": 8},
    {"lang": "de", "aspect": "1:1", "length": 8},
]


def ok(result):
    """The skill's own context block from a successful envelope."""
    assert result["success"] is True, result
    return result["context"]


def failed(result):
    """Assert the envelope is a failure and return its searchable text."""
    assert result["success"] is False, result
    return result["message"] + result.get("context", {}).get("traceback", "")


def load_skill(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Variable substitution
# ---------------------------------------------------------------------------


def test_a_whole_value_placeholder_keeps_the_variable_type():
    # A duration declared as a number must arrive as a number: stringifying it
    # and hoping the compile re-parses the text is how a template loses a
    # fractional frame rate.
    document = {"duration": "{{length}}", "fps": "{{rate}}", "muted": "{{flag}}"}
    variables = {"length": 8, "rate": 29.97, "flag": True}

    assert substitute_variables(document, variables) == {
        "duration": 8,
        "fps": 29.97,
        "muted": True,
    }


def test_a_placeholder_inside_a_larger_string_is_interpolated():
    document = {"path": "clips/{{lang}}/a.mp4", "name": "{{lang}}-{{aspect}}"}
    assert substitute_variables(document, {"lang": "zh", "aspect": "9:16"}) == {
        "path": "clips/zh/a.mp4",
        "name": "zh-9:16",
    }


def test_an_undeclared_variable_names_the_field_it_came_from():
    with pytest.raises(ValueError, match=r"template\.path uses undeclared variable 'lang'"):
        substitute_variables({"path": "clips/{{lang}}/a.mp4"}, {"langx": "zh"})


def test_a_malformed_placeholder_is_never_left_in_the_output():
    # A typo that rendered as literal text would silently import the wrong file.
    for bad in ("{{ lang", "{{l ang}}", "{{}}"):
        with pytest.raises(ValueError, match="malformed placeholder"):
            substitute_variables({"path": f"clips/{bad}/a.mp4"}, {"lang": "zh"})


def test_a_boolean_cannot_be_interpolated_into_text():
    with pytest.raises(ValueError, match="only strings and numbers"):
        substitute_variables({"path": "clips/{{lang}}/a.mp4"}, {"lang": True})


def test_a_variable_cannot_inject_structure():
    # A whole-value placeholder is the one place a variable could rewrite the
    # shape of the plan rather than its values. That is not templating.
    with pytest.raises(ValueError, match="must be a scalar, not dict"):
        substitute_variables({"duration": "{{length}}"}, {"length": {"start": 0}})


def test_substitution_walks_lists_and_nested_objects():
    document = {"tracks": [{"clips": [{"media": "{{clip}}", "start": 0}]}]}
    assert (
        substitute_variables(document, {"clip": "a.mp4"})["tracks"][0]["clips"][0]["media"]
        == "a.mp4"
    )


def test_a_document_without_placeholders_is_untouched():
    document = {"name": "plain", "tracks": []}
    assert substitute_variables(document, {"lang": "zh"}) == document


# ---------------------------------------------------------------------------
# Reframe
# ---------------------------------------------------------------------------


def one_item(**overrides: object) -> dict:
    """Render the shared template once, with the given fields overridden.

    The template's own ``aspect_ratio`` is a placeholder, so an override that
    leaves it alone has to be fed a real preset value -- otherwise the variable
    set hands the literal ``{{aspect}}`` straight to the recipe compiler.
    """
    template = dict(TEMPLATE, **overrides)
    aspect = str(template["aspect_ratio"])
    variables = {"lang": "en", "aspect": "9:16" if "{{" in aspect else aspect, "length": 4}
    return build_batch(template, [variables])["items"][0]


def rendered(reframe: dict, aspect: str = "9:16") -> dict:
    """The reframe report for one item -- or None plus the error, for the
    refusal cases, which assert on the message themselves."""
    return one_item(aspect_ratio=aspect, reframe=reframe)["reframe"]


def test_contain_fits_the_whole_frame_and_reports_the_bars():
    report = rendered({"fit": "contain", "source_aspect_ratio": "16:9"})

    assert report["cropped"] is False
    assert report["visible_source_fraction"] == {"width": 1.0, "height": 1.0}
    # 16:9 into 1080x1920: the picture is 1080 wide, 607.5 tall, so 1312.5px
    # of the canvas is bar. The report says so instead of leaving it implicit.
    assert report["bars"] == {"horizontal": 0.0, "vertical": 1312.5}
    assert report["scale"] == 67.5


def test_contain_into_a_square_canvas_bars_the_same_axis_as_the_fit():
    report = rendered({"fit": "contain", "source_aspect_ratio": "16:9"}, aspect="1:1")

    assert report["bars"] == {"horizontal": 0.0, "vertical": 472.5}
    assert report["cropped"] is False


def test_cover_crops_and_reports_how_much_of_the_source_survives():
    report = rendered({"fit": "cover", "source_aspect_ratio": "16:9", "safe_area": 0.3})

    assert report["cropped"] is True
    # (9/16) / (16/9) of the source width survives the fill.
    assert report["visible_source_fraction"] == {"width": 0.316406, "height": 1.0}
    assert report["safe_area"] == 0.3
    assert report["safe_area_preserved"] is True


def test_cover_into_the_declared_safe_area_is_refused():
    item = one_item(reframe={"fit": "cover", "source_aspect_ratio": "16:9", "safe_area": 0.6})

    assert item["state"] == "failed"
    assert "would crop into the declared safe area" in item["error"]
    assert "31.6%" in item["error"] and "60.0%" in item["error"]


def test_cover_without_a_safe_area_is_refused():
    # The whole point: the adapter will not crop when nobody said what is safe.
    item = one_item(reframe={"fit": "cover", "source_aspect_ratio": "16:9"})

    assert item["state"] == "failed"
    assert "requires safe_area" in item["error"]


def test_a_safe_area_on_a_fit_that_never_crops_is_refused():
    assert "safe_area is only meaningful with fit='cover'" in error_for(
        reframe={"fit": "contain", "safe_area": 0.9}
    )


def test_an_unknown_fit_is_refused():
    assert "fit must be one of" in error_for(
        reframe={"fit": "stretch", "source_aspect_ratio": "16:9"}
    )


def test_a_safe_area_outside_the_unit_range_is_refused():
    for bad in (0, -0.1, 1.5):
        assert r"safe_area must be in (0, 1]" in error_for(
            reframe={"fit": "cover", "source_aspect_ratio": "16:9", "safe_area": bad}
        )


def test_an_unsupported_reframe_field_is_refused():
    assert "unsupported fields: ['zoom']" in error_for(reframe={"fit": "contain", "zoom": 1.2})


def test_a_malformed_aspect_ratio_is_refused():
    for bad in ("16", "16:", "a:b"):
        assert "must look like '16:9'" in error_for(
            reframe={"fit": "contain", "source_aspect_ratio": bad}
        )
    assert "must carry positive integers" in error_for(
        reframe={"fit": "contain", "source_aspect_ratio": "0:9"}
    )
    # A bare float is not an aspect this adapter can name either: the presets
    # and every host setting speak 'W:H'.
    assert "must be a 'W:H' string" in error_for(
        reframe={"fit": "contain", "source_aspect_ratio": 1.77}
    )


def test_no_reframe_declared_means_none_was_applied():
    item = one_item(reframe=None)

    assert item["state"] == "pending"
    assert item["reframe"] is None


def test_a_declared_aspect_that_disagrees_with_the_canvas_is_refused():
    # The canvas is chosen by the preset a recipe names, so a plan carrying a
    # second, contradicting aspect is an authoring error, not a silent pick.
    document = {
        "schema": "dcc-mcp-capcut/edit-plan/v1",
        "name": "x",
        "fps": 30,
        "width": 1920,
        "height": 1080,
        "tracks": [
            {
                "name": "V",
                "kind": "Video",
                "clips": [{"name": "c", "media": "a.mp4", "start": 0, "duration": 30}],
            }
        ],
        "output": {"path": "o.mp4", "aspect_ratio": "9:16"},
    }
    with pytest.raises(ValueError, match="disagrees with the canvas"):
        render_template(document, {})


# ---------------------------------------------------------------------------
# Export preset
# ---------------------------------------------------------------------------


def exported(export: dict, aspect: str = "9:16") -> dict:
    return one_item(aspect_ratio=aspect, export=export)["export"]


def error_for(**overrides: object) -> str:
    """The reason one item was failed.

    ``build_batch`` isolates a bad variant instead of raising, so a refusal is
    asserted on the item it belongs to -- that isolation is itself the contract
    under test.
    """
    item = one_item(**overrides)
    assert item["state"] == "failed", f"expected a failure, got {item['state']}"
    return item["error"]


def test_without_a_preset_the_canvas_is_the_delivery_size():
    item = one_item(export=None)

    assert item["state"] == "pending"
    assert item["export"] == {"width": 1080, "height": 1920, "fps": 30.0}


def test_a_preset_carries_the_declared_encode_settings():
    assert exported({"format": "mov", "codec": "prores", "bitrate_mbps": 40, "audio": False}) == {
        "width": 1080,
        "height": 1920,
        "fps": 30.0,
        "format": "mov",
        "codec": "prores",
        "bitrate_mbps": 40.0,
        "audio": False,
    }


def test_a_smaller_delivery_size_is_allowed_while_the_aspect_holds():
    assert exported({"width": 540, "height": 960})["width"] == 540


def test_an_export_size_of_another_aspect_is_refused():
    # That is a reframe, and reframe is where the safe area gets checked.
    assert "does not match the canvas" in error_for(export={"width": 640, "height": 480})


def test_half_a_delivery_size_is_refused():
    assert "must be declared together" in error_for(export={"width": 640})


def test_unknown_encode_vocabulary_is_refused():
    assert "format must be one of" in error_for(export={"format": "avi"})
    assert "codec must be one of" in error_for(export={"codec": "vp9"})
    assert "bitrate_mbps must be a finite number > 0" in error_for(export={"bitrate_mbps": 0})
    assert "audio must be a boolean" in error_for(export={"audio": "yes"})
    assert "unsupported fields: ['crf']" in error_for(export={"crf": 18})


def test_the_preset_reaches_the_action_script():
    from dcc_mcp_capcut.editplan import compile_plan, plan_to_actions

    document = substitute_variables(
        dict(
            TEMPLATE,
            reframe=None,
            output_path="o.mp4",
            aspect_ratio="16:9",
            export={"codec": "h265", "bitrate_mbps": 20, "audio": False},
        ),
        {"lang": "en", "aspect": "16:9", "length": 4},
    )
    plan = compile_plan(document, fps=30)
    script = plan_to_actions(plan, export=True)
    export_step = [step for step in script["actions"] if step["action"] == "export_video"][0]

    assert export_step["params"]["codec"] == "h265"
    assert export_step["params"]["bitrate_mbps"] == 20
    assert export_step["params"]["audio"] is False
    assert export_step["params"]["width"] == 1920


# ---------------------------------------------------------------------------
# Batch building: failure isolation starts at compile time
# ---------------------------------------------------------------------------


def test_a_template_without_subtitles_still_renders():
    """Regression: a batch of plans that carry no subtitles.

    A compiled plan carries ``subtitles: []``, and that empty list used to be
    rejected by the next validation it met, so ``plan_to_actions`` raised for
    every plan with no subtitle file -- which is most batches. Rendering a
    template walks exactly that path.
    """
    template = dict(TEMPLATE)
    template.pop("subtitle_files")

    manifest = build_batch(
        template, [{"lang": "en", "aspect": "9:16", "length": 4}], require_output=False
    )

    assert manifest["items"][0]["state"] == "pending"
    assert manifest["items"][0]["plan"]["subtitles"] == []


def test_one_bad_variable_set_does_not_take_the_batch_with_it():
    variables = VARIABLES + [{"lang": "fr", "aspect": "9:16"}]  # no 'length'

    manifest = build_batch(TEMPLATE, variables)
    counts = item_counts(manifest)

    assert counts == {"pending": 3, "running": 0, "done": 0, "failed": 1, "skipped": 0}
    assert manifest["items"][3]["error"] == (
        "template.media[0].duration uses undeclared variable 'length'; declared: aspect, lang"
    )


def test_a_plan_without_a_destination_is_failed_only_when_output_is_required():
    template = dict(TEMPLATE)
    template.pop("output_path")

    inspect = build_batch(template, [VARIABLES[0]], require_output=False)
    runnable = build_batch(template, [VARIABLES[0]], require_output=True)

    assert inspect["items"][0]["state"] == "pending"
    assert runnable["items"][0]["state"] == "failed"
    assert "no output.path" in runnable["items"][0]["error"]


def test_every_item_carries_its_own_variables_and_output_path():
    manifest = build_batch(TEMPLATE, VARIABLES)

    assert [item["output_path"] for item in manifest["items"]] == [
        "out/promo_en_16:9.mp4",
        "out/promo_zh_9:16.mp4",
        "out/promo_de_1:1.mp4",
    ]
    assert manifest["items"][1]["variables"] == VARIABLES[1]
    assert manifest["items"][1]["name"] == "promo zh 9:16"


def test_two_items_may_not_render_to_the_same_destination():
    """A shared output path is a silent loss, so it is a build failure.

    The second render overwrites the first, and because each receipt is bound
    to the destination its item asked for, both still match -- the batch would
    report every item delivered while only the last render exists. Found at
    build time, before any render is spent.
    """
    template = dict(TEMPLATE, output_path="out/promo.mp4")  # no {{lang}}

    manifest = build_batch(template, VARIABLES)

    assert [item["state"] for item in manifest["items"]] == ["pending", "failed", "failed"]
    assert "already used by item 0" in manifest["items"][1]["error"]
    assert "overwrites the earlier one" in manifest["items"][2]["error"]
    # The first item keeps its destination; it is the one that would survive.
    assert manifest["items"][0]["output_path"] == "out/promo.mp4"


def test_a_duplicate_destination_is_also_reported_while_inspecting():
    # Inspection is the cheap moment to find this, so the collision is
    # reported there too rather than only once a batch starts rendering.
    template = dict(TEMPLATE, output_path="out/promo.mp4")

    manifest = build_batch(template, VARIABLES, require_output=False)

    assert [item["state"] for item in manifest["items"]] == ["pending", "failed", "failed"]


def test_building_rejects_a_variables_list_that_is_not_a_list_of_objects():
    with pytest.raises(ValueError, match="nonempty list of objects"):
        build_batch(TEMPLATE, [])
    with pytest.raises(ValueError, match=r"variables\[0\] must be an object"):
        build_batch(TEMPLATE, ["en"])


def test_a_preset_of_another_aspect_is_refused_by_the_assembly_link_too():
    """Both links must give the same verdict for one document.

    ``apply_edit_plan(export=True)`` lowers a plan to an ``export_video``
    action, so a preset the batch link refuses must not be dispatched as a
    distorted encode by the assembly link. The rules have one owner.
    """
    from dcc_mcp_capcut.delivery import EXPORT_CODECS, EXPORT_FORMATS

    canvas = {
        "schema": "dcc-mcp-capcut/edit-plan/v1",
        "name": "x",
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "tracks": [
            {
                "name": "V",
                "kind": "Video",
                "clips": [{"name": "c", "media": "a.mp4", "start": 0, "duration": 30}],
            }
        ],
        "output": {"path": "o.mp4"},
    }

    # A compile-time verdict, not one that only appears when a link asks.
    with pytest.raises(ValueError, match="does not match the canvas"):
        compile_plan(
            dict(canvas, output={"path": "o.mp4", "export": {"width": 640, "height": 480}})
        )
    with pytest.raises(ValueError, match="must be declared together"):
        compile_plan(dict(canvas, output={"path": "o.mp4", "export": {"width": 640}}))
    with pytest.raises(ValueError, match="codec must be one of"):
        compile_plan(dict(canvas, output={"path": "o.mp4", "export": {"codec": "vp9"}}))

    # A valid preset is lowered with the canvas filling in what it omits.
    plan = compile_plan(dict(canvas, output={"path": "o.mp4", "export": {"codec": "h265"}}))
    step = [
        s for s in plan_to_actions(plan, export=True)["actions"] if s["action"] == "export_video"
    ]
    assert step[0]["params"] == {
        "timeline_id": "$timeline",
        "output_path": "o.mp4",
        "width": 1080,
        "height": 1920,
        "fps": 30.0,
        "codec": "h265",
    }
    assert EXPORT_FORMATS and EXPORT_CODECS


# ---------------------------------------------------------------------------
# Manifest: the resume record
# ---------------------------------------------------------------------------


def test_a_manifest_survives_a_round_trip(tmp_path):
    manifest = build_batch(TEMPLATE, VARIABLES)
    path = tmp_path / "batch.json"

    save_batch(str(path), manifest)
    restored = load_batch(str(path))

    assert restored == manifest


def test_an_existing_file_is_never_replaced_by_a_fresh_run(tmp_path):
    """The overwrite guard tests existence, not parseability.

    A truncated manifest or an unrelated file at the path is still a file the
    caller did not ask to have replaced: inferring "absent" from a parse
    failure would let a fresh batch silently destroy the record of renders
    already paid for.
    """
    path = tmp_path / "batch.json"
    path.write_text("{not json at all", encoding="utf-8")

    with pytest.raises(ValueError, match="already exists"):
        fresh_overwrite_check(str(path))


def test_a_corrupt_manifest_is_refused_rather_than_repaired(tmp_path):
    path = tmp_path / "batch.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot read batch manifest"):
        load_batch(str(path))


def test_a_manifest_of_the_wrong_schema_is_refused(tmp_path):
    path = tmp_path / "batch.json"
    path.write_text(json.dumps({"schema": "other/v1", "items": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported schema"):
        load_batch(str(path))


def test_a_manifest_carrying_an_unknown_item_state_is_refused(tmp_path):
    path = tmp_path / "batch.json"
    path.write_text(
        json.dumps({"schema": BATCH_SCHEMA, "items": [{"state": "zombie"}]}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="unknown state"):
        load_batch(str(path))


def test_saving_replaces_rather_than_truncating(tmp_path):
    # A crash between truncate and write would leave a manifest that is not
    # JSON, and the batch -- every render already paid for -- unresumable.
    path = tmp_path / "batch.json"
    save_batch(str(path), build_batch(TEMPLATE, VARIABLES[:1]))
    save_batch(str(path), build_batch(TEMPLATE, VARIABLES))

    assert len(load_batch(str(path))["items"]) == 3
    assert not (tmp_path / "batch.json.tmp").exists()


# ---------------------------------------------------------------------------
# Item state machine
# ---------------------------------------------------------------------------


def test_an_item_moves_from_pending_to_done_with_its_proof():
    manifest = build_batch(TEMPLATE, VARIABLES[:1])
    receipt = {"path": "out/promo_en_16:9.mp4", "exists": True, "size_bytes": 4096}

    begin_item(manifest, 0)
    assert manifest["items"][0]["state"] == "running"
    complete_item(manifest, 0, timeline_id="tl-1", job_id="job-1", receipt=receipt)

    item = manifest["items"][0]
    assert item["state"] == "done"
    assert item["attempts"] == 1
    assert item["timeline_id"] == "tl-1" and item["job_id"] == "job-1"
    assert item["receipt"] is receipt
    assert summarize(manifest)["complete"] is True


def test_a_failed_item_keeps_its_reason_and_the_rest_keep_their_state():
    manifest = build_batch(TEMPLATE, VARIABLES)

    complete_item(manifest, 0)
    fail_item(manifest, 1, RuntimeError("bridge did not respond"))
    skip_item(manifest, 2, "batch stopped")

    states = [item["state"] for item in manifest["items"]]
    assert states == ["done", "failed", "skipped"]
    assert manifest["items"][1]["error"] == "bridge did not respond"
    assert summarize(manifest)["complete"] is False


def test_a_delivered_item_is_never_selected_again():
    manifest = build_batch(TEMPLATE, VARIABLES)
    complete_item(manifest, 0)
    fail_item(manifest, 1, "boom")

    assert select_items(manifest) == [2]
    assert select_items(manifest, retry_failed=True) == [1, 2]


def test_skipping_only_touches_items_that_were_never_attempted():
    manifest = build_batch(TEMPLATE, VARIABLES)
    complete_item(manifest, 0)

    skip_item(manifest, 0, "too late")

    assert manifest["items"][0]["state"] == "done"


def test_an_out_of_range_index_is_refused():
    manifest = build_batch(TEMPLATE, VARIABLES[:1])

    with pytest.raises(ValueError, match="has no item"):
        begin_item(manifest, 7)


def test_the_summary_reports_one_verdict_per_item():
    manifest = build_batch(TEMPLATE, VARIABLES)
    complete_item(manifest, 0, receipt={"size_bytes": 1})
    fail_item(manifest, 2, "nope")

    summary = summarize(manifest)

    assert summary["counts"] == {"pending": 1, "running": 0, "done": 1, "failed": 1, "skipped": 0}
    assert summary["items"][0]["state"] == "done"
    assert summary["items"][2]["error"] == "nope"


# ---------------------------------------------------------------------------
# Skill: render_batch_template
# ---------------------------------------------------------------------------


@pytest.fixture
def render_skill():
    return load_skill("render_batch_template")


def test_render_returns_every_variant_without_a_host(render_skill):
    context = ok(render_skill.main(template=TEMPLATE, variables=VARIABLES))

    assert context["total"] == 3
    assert context["counts"]["failed"] == 0
    assert len(context["plans"]) == 3
    # Each variant is the canvas its variable set asked for.
    assert [plan["width"] for plan in context["plans"]] == [1920, 1080, 1080]
    assert [plan["height"] for plan in context["plans"]] == [1080, 1920, 1080]
    assert context["reframes"][1]["bars"]["vertical"] == 1312.5


def test_render_reports_failures_per_item_instead_of_aborting(render_skill):
    variables = VARIABLES + [{"lang": "fr", "aspect": "9:16"}]

    context = ok(render_skill.main(template=TEMPLATE, variables=variables))

    assert context["counts"]["failed"] == 1
    assert context["items"][3]["error"].startswith("template.media[0].duration")


def test_render_requires_a_template_and_variables(render_skill):
    assert "template is required" in failed(render_skill.main(variables=VARIABLES))
    assert "variables is required" in failed(render_skill.main(template=TEMPLATE))


# ---------------------------------------------------------------------------
# Skill: run_batch
# ---------------------------------------------------------------------------


class FakeHost:
    """A recording stand-in for the bridge.

    Every host call in a batch goes through ``dcc_mcp_capcut.assemble``, so one
    patch covers the assembly walk, the export submit and the status polls.
    """

    def __init__(
        self,
        *,
        fail_export_for=(),
        omit_job_id_for=(),
        no_receipt_for=(),
        stalled_jobs=(),
    ):
        self.calls: list[tuple[str, dict]] = []
        self.fail_export_for = set(fail_export_for)
        self.omit_job_id_for = set(omit_job_id_for)
        self.no_receipt_for = set(no_receipt_for)
        # Jobs that never finish: the only way to exercise the wait budget. A
        # host that stalls is a real failure mode, and the item must fail with
        # a message that says the job is still running rather than time out the
        # whole batch.
        self.stalled_jobs = set(stalled_jobs)
        self.exports = 0
        self.polls: list[str] = []
        self.destinations: dict[str, str] = {}
        # Per-job fields merged into the receipt, to make an honest-looking
        # receipt that is wrong in one field. ``path`` is the interesting one:
        # it lets a host describe a different artifact than it was given.
        self.receipt_overrides: dict[str, dict] = {}

    def __call__(self, action, params, **_kwargs):
        self.calls.append((action, params))
        if action == "apply_edit_plan":
            # A host that does not implement the batch action, which is the
            # realistic case: the adapter falls back to the composed walk.
            raise RuntimeError("Unsupported action: apply_edit_plan")
        if action == "import_media":
            return {"verification": {"ok": True}, "media_id": f"m-{len(self.calls)}"}
        if action == "create_timeline":
            return {"verification": {"ok": True, "timeline": TIMELINE}, "timeline_id": "tl-1"}
        if action == "add_clip":
            return {
                "verification": {"ok": True, "timeline": TIMELINE},
                "clip_id": f"clip-{len(self.calls)}",
            }
        if action == "import_subtitles":
            return {"verification": {"ok": True, "timeline": TIMELINE}, "caption_ids": ["c-1"]}
        if action == "export_video":
            self.exports += 1
            path = params["output_path"]
            if path in self.omit_job_id_for:
                return {"verification": {"ok": True}, "output_path": path}
            job_id = f"job-{self.exports}"
            # The destination each job was submitted for, so the receipt this
            # host hands back describes the artifact the item asked for -- a
            # receipt for a different path has to fail the item, not pass it.
            self.destinations[job_id] = path
            return {
                "verification": {"ok": True},
                "job_id": job_id,
                "output_path": path,
            }
        if action == "get_export_status":
            self.polls.append(params["job_id"])
            if params["job_id"] in self.stalled_jobs:
                return {"state": "running", "progress": 0.4}
            state = "failed" if params["job_id"] in self.fail_export_for else "done"
            result = {"state": state, "progress": 1.0}
            if params.get("verify_output") is True:
                result["verification"] = {"ok": True}
                if params["job_id"] not in self.no_receipt_for:
                    result["verification"]["output"] = {
                        "path": self.destinations[params["job_id"]],
                        "exists": True,
                        "size_bytes": 2048,
                        "duration_sec": 8.0,
                        "streams": [
                            {"kind": "video", "codec": "h264", "width": 1080, "height": 1920}
                        ],
                        **self.receipt_overrides.get(params["job_id"], {}),
                    }
            return result
        return {"verification": {"ok": True, "timeline": TIMELINE}}


@pytest.fixture
def run_skill(monkeypatch):
    """The batch runner with the bridge, the clock and the sleep all faked."""
    module = load_skill("run_batch")
    host = FakeHost()

    monkeypatch.setattr(assemble_module, "call_bridge", host)
    monkeypatch.setattr(module, "_SLEEP", lambda _seconds: None)
    # A clock that never advances: the fake host is always terminal, so a real
    # one would only make the tests depend on wall time.
    monkeypatch.setattr(module, "_CLOCK", lambda: 0.0)
    module.host = host
    return module


@pytest.fixture
def media_dir(tmp_path):
    """A delivery root holding every file every variant references."""
    for lang in ("en", "zh", "de"):
        (tmp_path / "clips" / lang).mkdir(parents=True, exist_ok=True)
        (tmp_path / "clips" / lang / "a.mp4").write_bytes(b"\x00")
        (tmp_path / "subs").mkdir(exist_ok=True)
        (tmp_path / "subs" / f"{lang}.srt").write_bytes(b"\x00")
    return tmp_path


def test_a_batch_delivers_every_item_and_receipts_each_one(run_skill, media_dir, tmp_path):
    manifest = tmp_path / "batch.json"

    context = ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(manifest),
        )
    )

    assert context["counts"] == {"pending": 0, "running": 0, "done": 3, "failed": 0, "skipped": 0}
    assert context["complete"] is True
    # One receipt per item, each bound to the destination that item asked for:
    # a host handing back another item's probe must fail, not pass.
    assert [item["receipt"]["path"] for item in context["items"]] == [
        "out/promo_en_16:9.mp4",
        "out/promo_zh_9:16.mp4",
        "out/promo_de_1:1.mp4",
    ]
    assert all(item["receipt"]["exists"] for item in context["items"])
    assert manifest.is_file()


def test_each_item_is_assembled_and_exported_once(run_skill, media_dir, tmp_path):
    ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(tmp_path / "batch.json"),
        )
    )
    actions = [action for action, _ in run_skill.host.calls]

    assert actions.count("export_video") == 3
    assert actions.count("create_timeline") == 3
    # Two polls per item: one that finds the terminal state, one that asks for
    # the receipt. Never a flagged poll before the job is terminal.
    assert actions.count("get_export_status") == 6
    assert run_skill.host.polls == ["job-1", "job-1", "job-2", "job-2", "job-3", "job-3"]


def test_the_declared_export_preset_reaches_the_host(run_skill, media_dir, tmp_path):
    ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES[:1],
            media_dir=str(media_dir),
            manifest_path=str(tmp_path / "batch.json"),
        )
    )
    params = [p for action, p in run_skill.host.calls if action == "export_video"][0]

    assert params["codec"] == "h264"
    assert params["bitrate_mbps"] == 12
    assert params["width"] == 1920 and params["height"] == 1080
    assert params["output_path"] == "out/promo_en_16:9.mp4"


def test_one_failing_item_does_not_stop_the_batch(run_skill, media_dir, tmp_path):
    monkeypatch_free = run_skill.host
    monkeypatch_free.fail_export_for = {"job-2"}

    context = ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(tmp_path / "batch.json"),
        )
    )

    assert [item["state"] for item in context["items"]] == ["done", "failed", "done"]
    assert "finished in state 'failed'" in context["items"][1]["error"]
    assert context["counts"]["done"] == 2
    # The failure is on disk too, which is what makes it resumable.
    assert load_batch(str(tmp_path / "batch.json"))["items"][1]["state"] == "failed"


def test_a_failed_item_is_reported_even_when_the_batch_stops_there(run_skill, media_dir, tmp_path):
    run_skill.host.fail_export_for = {"job-1"}

    context = ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(tmp_path / "batch.json"),
            continue_on_error=False,
        )
    )

    assert [item["state"] for item in context["items"]] == ["failed", "skipped", "skipped"]
    assert run_skill.host.exports == 1
    assert "continue_on_error is false" in context["items"][2]["error"]


def test_an_item_that_cannot_be_compiled_is_never_dispatched(run_skill, media_dir, tmp_path):
    variables = VARIABLES + [{"lang": "fr", "aspect": "9:16"}]

    context = ok(
        run_skill.main(
            template=TEMPLATE,
            variables=variables,
            media_dir=str(media_dir),
            manifest_path=str(tmp_path / "batch.json"),
        )
    )

    assert context["items"][3]["state"] == "failed"
    assert "undeclared variable 'length'" in context["items"][3]["error"]
    assert run_skill.host.exports == 3


def test_an_export_without_a_job_id_fails_only_that_item(run_skill, media_dir, tmp_path):
    run_skill.host.omit_job_id_for = {"out/promo_zh_9:16.mp4"}

    context = ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(tmp_path / "batch.json"),
        )
    )

    assert [item["state"] for item in context["items"]] == ["done", "failed", "done"]
    assert "without a job_id" in context["items"][1]["error"]


def test_a_missing_receipt_fails_the_item_when_verification_is_asked_for(
    run_skill, media_dir, tmp_path
):
    run_skill.host.no_receipt_for = {"job-2"}

    context = ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(tmp_path / "batch.json"),
        )
    )

    assert context["items"][1]["state"] == "failed"
    # The message is the receipt contract's own: it names the action and the
    # field, so an operator looking at one failed item knows what is missing.
    assert "verification.output" in context["items"][1]["error"]
    # The items around it are unaffected.
    assert [item["state"] for item in context["items"]] == ["done", "failed", "done"]


def test_a_receipt_for_another_artifact_fails_the_item(run_skill, media_dir, tmp_path):
    """The batch-only part of the receipt check.

    A single export binds the receipt to the ``output_path`` the same result
    carries, and ``get_export_status`` usually carries none -- so a host that
    reports a perfectly well-formed receipt for the *previous* item would pass
    every field check. Batch knows the destination each item asked for, so it
    binds the receipt to it and refuses the mismatch.
    """
    run_skill.host.receipt_overrides = {
        "job-2": {"path": "out/promo_en_16:9.mp4"}  # the previous item's render
    }

    context = ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(tmp_path / "batch.json"),
        )
    )

    assert context["items"][1]["state"] == "failed"
    assert "was asked to produce" in context["items"][1]["error"]
    assert [item["state"] for item in context["items"]] == ["done", "failed", "done"]


def test_a_receipt_for_a_missing_file_fails_the_item(run_skill, media_dir, tmp_path):
    # A receipt that does not prove the file exists is not a receipt -- the
    # exact failure that per-item receipts exist to catch in a batch.
    run_skill.host.receipt_overrides = {"job-2": {"exists": False, "size_bytes": 0}}

    context = ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(tmp_path / "batch.json"),
        )
    )

    assert context["items"][1]["state"] == "failed"
    assert "does not prove the artifact exists" in context["items"][1]["error"]


def test_without_verification_the_hosts_word_is_accepted(run_skill, media_dir, tmp_path):
    run_skill.host.no_receipt_for = {"job-2"}

    context = ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(tmp_path / "batch.json"),
            verify_output=False,
        )
    )

    assert context["complete"] is True
    assert context["items"][1]["receipt"] is None
    # One poll per item when nothing asks for a receipt.
    assert run_skill.host.polls == ["job-1", "job-2", "job-3"]


def test_resume_keeps_delivered_items_and_retries_failures(run_skill, media_dir, tmp_path):
    manifest = tmp_path / "batch.json"
    run_skill.host.fail_export_for = {"job-2"}
    ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(manifest),
        )
    )
    assert run_skill.host.exports == 3

    # The cause is fixed; the second run must render only what is missing.
    run_skill.host.fail_export_for = set()
    context = ok(run_skill.main(manifest_path=str(manifest), resume=True))

    assert context["complete"] is True
    assert [item["state"] for item in context["items"]] == ["done", "done", "done"]
    # The failed item's own job is asked about first and reported done, so it
    # is settled from the render the first run already paid for -- a resume
    # must not submit a second export to a destination that already has one.
    assert run_skill.host.exports == 3
    assert context["items"][1]["receipt"]["path"] == "out/promo_zh_9:16.mp4"


def test_a_resume_renders_again_only_when_the_orphan_job_ended(run_skill, media_dir, tmp_path):
    """The three things an interrupted job can turn out to be."""
    manifest = tmp_path / "batch.json"
    run_skill.host.fail_export_for = {"job-2"}
    ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(manifest),
        )
    )
    assert load_batch(str(manifest))["items"][1]["error"]

    # The abandoned job is reported done: settle it, render nothing.
    run_skill.host.fail_export_for = set()
    context = ok(run_skill.main(manifest_path=str(manifest), resume=True))
    assert context["counts"] == {"pending": 0, "running": 0, "done": 3, "failed": 0, "skipped": 0}
    assert run_skill.host.exports == 3


def test_a_resume_never_joins_a_job_that_is_still_running(run_skill, media_dir, tmp_path):
    manifest = tmp_path / "batch.json"
    run_skill.host.stalled_jobs = {"job-2"}
    ticks = iter(range(0, 100_000, 1_000))
    run_skill._CLOCK = lambda: next(ticks)
    ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(manifest),
        )
    )
    # The job the first run gave up on is still rendering host-side.
    assert run_skill.host.exports == 2

    result = run_skill.main(manifest_path=str(manifest), resume=True)

    # Refused before dispatching anything, and it names the job that holds the
    # window. A second export to that destination would overwrite the first.
    assert result["success"] is False
    assert "still has export job 'job-2'" in result["message"]
    assert run_skill.host.exports == 2


def test_a_failed_item_without_a_job_is_reattempted_normally(run_skill, media_dir, tmp_path):
    # An item that failed before its export was submitted has no job to ask
    # about, so there is nothing to settle and nothing to wait for.
    manifest = tmp_path / "batch.json"
    run_skill.host.omit_job_id_for = {"out/promo_zh_9:16.mp4"}
    ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(manifest),
        )
    )
    assert load_batch(str(manifest))["items"][1]["job_id"] is None

    run_skill.host.omit_job_id_for = set()
    context = ok(run_skill.main(manifest_path=str(manifest), resume=True))

    assert context["complete"] is True
    assert run_skill.host.exports == 4


def test_resume_does_not_need_the_template_again(run_skill, media_dir, tmp_path):
    manifest = tmp_path / "batch.json"
    ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES[:1],
            media_dir=str(media_dir),
            manifest_path=str(manifest),
        )
    )

    context = ok(run_skill.main(manifest_path=str(manifest), resume=True))

    assert context["counts"]["done"] == 1
    assert run_skill.host.exports == 1  # nothing was re-rendered


def test_a_retry_after_a_late_failure_keeps_the_subtitle_alignment(run_skill, media_dir, tmp_path):
    """Dispatching must not mutate the stored plan.

    Stripping the adapter-side ``align``/``output_path`` directives is part of
    lowering. The manifest is saved after every item, so mutating the stored
    plan means a retry following a late failure imports the un-timed file
    instead of the re-timed one -- and reports success.
    """
    import copy as copy_module

    template = dict(TEMPLATE)
    template["subtitle_files"] = [
        {"file": "subs/{{lang}}.srt", "align": "sequence", "output_path": "subs/aligned.srt"}
    ]
    manifest = tmp_path / "batch.json"
    item = build_batch(template, [{"lang": "en", "aspect": "16:9", "length": 4}])["items"][0]
    assert item["state"] != "failed", item["error"]
    authored = copy_module.deepcopy(item["plan"])

    # Fail the item after assembly, the way a real render failure would.
    run_skill.host.fail_export_for = {"job-1"}
    ok(
        run_skill.main(
            template=template,
            variables=[{"lang": "en", "aspect": "16:9", "length": 4}],
            media_dir=str(media_dir),
            manifest_path=str(manifest),
        )
    )

    stored = load_batch(str(manifest))["items"][0]["plan"]
    assert stored == authored, "the persisted plan lost the directives a retry needs"
    assert stored["subtitles"][0]["align"] == "sequence"


def test_a_build_failure_keeps_its_compile_reason_when_retried(run_skill, media_dir, tmp_path):
    # begin_item clears the previous error, so the compile verdict has to be
    # read before the item is marked running -- otherwise a resume replaces
    # "undeclared variable 'length'" with a contentless "did not compile".
    variables = [{"lang": "en", "aspect": "16:9"}]  # no 'length'

    context = ok(
        run_skill.main(
            template=TEMPLATE,
            variables=variables,
            media_dir=str(media_dir),
            manifest_path=str(tmp_path / "batch.json"),
        )
    )

    assert "undeclared variable 'length'" in context["items"][0]["error"]


def test_the_manifest_is_observable_before_the_first_item_finishes(run_skill, media_dir, tmp_path):
    # batch_status is the only way to watch a batch while it renders, which
    # means the manifest has to exist during item 0, not only after it.
    manifest = tmp_path / "batch.json"
    seen: list[bool] = []
    run_skill.host.stalled_jobs = {"job-1"}

    def no_sleep(_seconds):
        seen.append(manifest.exists())

    run_skill._SLEEP = no_sleep
    # Advanced in small steps so the item actually polls more than once: the
    # manifest has to be on disk during the wait, not only after it ends.
    ticks = iter(range(0, 100_000, 100))
    run_skill._CLOCK = lambda: next(ticks)

    ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES[:1],
            media_dir=str(media_dir),
            manifest_path=str(manifest),
        )
    )

    assert seen and all(seen), "the manifest was absent while the first item ran"


def test_resume_without_a_manifest_path_is_refused(run_skill):
    assert "resume=true requires manifest_path" in failed(run_skill.main(resume=True))


def test_a_fresh_run_never_overwrites_an_existing_manifest(run_skill, media_dir, tmp_path):
    manifest = tmp_path / "batch.json"
    ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES[:1],
            media_dir=str(media_dir),
            manifest_path=str(manifest),
        )
    )
    before = manifest.read_text(encoding="utf-8")

    message = failed(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(manifest),
        )
    )

    assert "already exists" in message
    assert manifest.read_text(encoding="utf-8") == before
    assert run_skill.host.exports == 1


def test_dry_run_compiles_everything_and_dispatches_nothing(run_skill, media_dir, tmp_path):
    manifest = tmp_path / "batch.json"

    context = ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(manifest),
            dry_run=True,
        )
    )

    assert context["dispatched"] is False
    assert context["total"] == 3
    assert run_skill.host.calls == []
    # A dry run promises to touch nothing, and that includes the manifest.
    assert not manifest.exists()


def test_media_dir_is_required_unless_the_run_is_a_dry_run(run_skill, media_dir):
    assert "media_dir is required" in failed(
        run_skill.main(template=TEMPLATE, variables=VARIABLES[:1])
    )


def test_the_batch_stops_waiting_when_an_item_overruns(run_skill, media_dir, tmp_path):
    run_skill.host.stalled_jobs = {"job-1"}
    # A clock that runs past the budget on the first check: the poll sees a
    # running job, the wait is already spent, and the item has to fail instead
    # of spinning until the host gives up.
    ticks = iter(range(0, 100_000, 1_000))
    run_skill._CLOCK = lambda: next(ticks)

    context = ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES[:1],
            media_dir=str(media_dir),
            manifest_path=str(tmp_path / "batch.json"),
        )
    )

    assert context["items"][0]["state"] == "failed"
    assert "did not reach a terminal state" in context["items"][0]["error"]
    assert "still running host-side" in context["items"][0]["error"]


def test_a_timed_out_item_stops_the_batch(run_skill, media_dir, tmp_path):
    """A render that overran its wait budget is still running.

    There is one bound CapCut window and that item is using it, so the next
    item cannot be dispatched. The failure is recorded first -- the manifest
    has to show which job is still out there -- and then the batch stops.
    """
    run_skill.host.stalled_jobs = {"job-1"}
    ticks = iter(range(0, 100_000, 1_000))
    run_skill._CLOCK = lambda: next(ticks)

    context = ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(tmp_path / "batch.json"),
        )
    )

    assert [item["state"] for item in context["items"]] == ["failed", "skipped", "skipped"]
    assert "did not reach a terminal state" in context["items"][0]["error"]
    assert "still rendering" in context["items"][1]["error"]
    # Only the first item was ever dispatched.
    assert run_skill.host.exports == 1
    assert "stopped" in context


def test_a_batch_needs_a_template_to_start(run_skill):
    assert "template is required" in failed(run_skill.main(variables=VARIABLES))


def test_the_poll_budget_is_validated(run_skill):
    assert "item_timeout_secs must be > 0" in failed(
        run_skill.main(template=TEMPLATE, variables=VARIABLES, item_timeout_secs=0)
    )
    assert "poll_interval_secs must be >= 0" in failed(
        run_skill.main(
            template=TEMPLATE, variables=VARIABLES, item_timeout_secs=10, poll_interval_secs=20
        )
    )


# ---------------------------------------------------------------------------
# Skill: batch_status
# ---------------------------------------------------------------------------


def test_batch_status_reads_the_manifest_back(run_skill, media_dir, tmp_path):
    manifest = tmp_path / "batch.json"
    ok(
        run_skill.main(
            template=TEMPLATE,
            variables=VARIABLES,
            media_dir=str(media_dir),
            manifest_path=str(manifest),
        )
    )

    status = load_skill("batch_status")
    context = ok(status.main(manifest_path=str(manifest)))

    assert context["total"] == 3
    assert context["counts"]["done"] == 3
    assert len(context["plans"]) == 3
    assert context["items"][1]["receipt"]["size_bytes"] == 2048
    assert context["items"][1]["receipt"]["path"] == "out/promo_zh_9:16.mp4"


def test_batch_status_requires_a_path():
    status = load_skill("batch_status")

    assert "manifest_path is required" in failed(status.main())


def test_batch_status_refuses_a_manifest_it_cannot_read(tmp_path):
    status = load_skill("batch_status")

    assert "cannot read batch manifest" in failed(
        status.main(manifest_path=str(tmp_path / "missing.json"))
    )
