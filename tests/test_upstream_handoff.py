"""The upstream handoff format is a promise to a system we do not control.

An upstream generator reads ``references/upstream-handoff.md`` and copies
``demo/upstream-delivery/``. Both rot silently: the document can describe a
manifest the example no longer produces, and the example can stop running while
the document still says it does.

These tests hold the promise:

- the reference document ships inside the package, where an agent can read it;
- the boundary statement stays aligned with ``host-boundary.md`` on the
  specific claims that matter to an upstream caller;
- the worked example actually runs end to end, host-free, on this platform;
- a delivery cannot write outside its own root.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from importlib.resources import files
from pathlib import Path

import pytest

from demo import upstream_handoff

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "demo" / "upstream-delivery"
REFERENCES = ROOT / "src" / "dcc_mcp_capcut" / "skills" / "references"

# Claims the two documents must agree on. Each is a phrase both already use,
# checked against both files: an upstream caller reads the handoff document
# rather than host-boundary.md, so a rewording is how the two start to
# disagree about what the adapter guarantees.
ALIGNED_BOUNDARY_CLAIMS = (
    "closed-source",
    "redistribut",
    "consent-gated",
    "loopback",
)


def asset(asset_id: str, path: str, kind: str = "video") -> dict:
    """A manifest entry. ``attribution``/``source`` are nulled, not omitted."""
    return {
        "id": asset_id,
        "path": path,
        "kind": kind,
        "license": "none",
        "attribution": None,
        "source": None,
    }


def manifest_declaring(*assets: dict) -> dict:
    """A manifest wrapping already-built asset entries."""
    return {
        "schema": upstream_handoff.MANIFEST_SCHEMA,
        "delivery_root": ".",
        "assets": list(assets),
    }


def plan_referencing(*media: str) -> dict:
    """A minimal valid canonical plan whose clips point at the given paths."""
    return {
        "schema": upstream_handoff.PLAN_SCHEMA,
        "name": "scratch",
        "fps": 30,
        "width": 1920,
        "height": 1080,
        "tracks": [
            {
                "name": "V1",
                "kind": "Video",
                "clips": [
                    {
                        "name": f"clip{index}",
                        "media": path,
                        "start": index * 30,
                        "duration": 30,
                        "media_duration": 30,
                    }
                    for index, path in enumerate(media)
                ],
            }
        ],
    }


def _symlinks_supported() -> bool:
    """Probe once whether this platform/process may create symlinks."""
    with tempfile.TemporaryDirectory() as probe:
        target = Path(probe) / "target"
        target.mkdir()
        try:
            (Path(probe) / "link").symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            return False
        return True


def delivery_copy(tmp_path: Path, *, with_media: bool = False) -> Path:
    """A scratch copy of the worked example, so a run never writes into the repo.

    ``assets/`` is dropped unless asked for. A previous run may have left
    placeholder media there (it is gitignored but present on disk), and tests
    that assert on placeholder behaviour must not inherit that state.
    """
    delivery = tmp_path / "delivery"
    shutil.copytree(EXAMPLE, delivery, ignore=shutil.ignore_patterns("assets"))
    if with_media:
        (delivery / "assets").mkdir()
        for name in ("earthrise.mp4", "oahu_flyover.mp4", "free_ambient.wav"):
            (delivery / "assets" / name).write_bytes(b"x")
    return delivery


def test_handoff_reference_ships_inside_the_package():
    source = (REFERENCES / "upstream-handoff.md").read_text(encoding="utf-8")
    packaged = files("dcc_mcp_capcut").joinpath("skills/references/upstream-handoff.md")
    assert packaged.is_file()
    assert packaged.read_text(encoding="utf-8") == source


def test_handoff_reference_restates_the_boundary_in_the_same_words():
    """An upstream caller reads this document, not host-boundary.md.

    So the boundary has to be restated here, in the same terms. A rewording is
    how the two documents start to disagree about what the adapter guarantees.
    """
    handoff = (REFERENCES / "upstream-handoff.md").read_text(encoding="utf-8")
    host_boundary = (REFERENCES / "host-boundary.md").read_text(encoding="utf-8")
    for claim in ALIGNED_BOUNDARY_CLAIMS:
        assert claim in handoff, f"upstream-handoff.md never states {claim!r}"
        assert claim in host_boundary, f"host-boundary.md no longer states {claim!r}"


def test_example_delivery_carries_both_handoff_documents():
    manifest = json.loads((EXAMPLE / "asset-manifest.json").read_text(encoding="utf-8"))
    plan = json.loads((EXAMPLE / "edit-plan.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == upstream_handoff.MANIFEST_SCHEMA
    assert plan["schema"] == upstream_handoff.PLAN_SCHEMA

    declared = upstream_handoff.declared_paths(manifest)
    referenced = upstream_handoff.referenced_paths(plan)
    # Referenced-but-undeclared is the failure reconcile() exists to catch, so
    # the checked-in example must not be that failure.
    assert [path for path in referenced if path not in declared] == []


def test_example_declares_every_required_manifest_field():
    manifest = json.loads((EXAMPLE / "asset-manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["assets"]:
        for field in ("id", "path", "kind", "license"):
            assert entry.get(field), f"asset {entry.get('id')!r} is missing {field!r}"
        # attribution/source are optional but must be present-and-null rather
        # than absent, so "nothing owed" is distinguishable from "unchecked".
        for field in ("attribution", "source"):
            assert field in entry, f"asset {entry['id']!r} omits {field!r} instead of nulling it"


def test_example_runs_end_to_end_host_free(tmp_path):
    """Stages 1-5 must run on any platform, including a CI runner with no host.

    This is the guard that keeps the example from becoming pseudocode: it is
    executed, not just present.
    """
    verdict = upstream_handoff.run(delivery_copy(tmp_path), dispatch=False)
    assert verdict["stage"] == "host-free complete"
    assert verdict["action_script"]["dispatched"] is False
    assert verdict["action_script"]["step_count"] > 0
    assert verdict["interchange"]["matches_duration"] is True
    # Nothing was dispatched, so no CapCut window was ever required.
    assert "dispatch" not in verdict


@pytest.mark.parametrize(
    "bad_path",
    [
        "../outside/escaped.txt",
        "C:/Windows/Temp/escaped.txt",
        "..\\outside\\escaped.txt",
        "assets/a%2Fb.mp4",
        "https://example.com/x.mp4",
    ],
)
def test_declared_paths_reject_a_non_portable_path(bad_path):
    """A manifest path must be portable before anything writes to it.

    ``materialize()`` creates files at declared paths, so an unvalidated
    traversing or absolute path would escape the delivery root. The plan's own
    media paths are already guarded by the canonical rule; these hold the
    manifest to the same one, because this example is the reference a
    downstream generator copies.
    """
    with pytest.raises(upstream_handoff.HandoffError, match="non-portable path"):
        upstream_handoff.declared_paths(manifest_declaring(asset("x", bad_path)))


def test_materialize_never_writes_outside_the_delivery_root(tmp_path):
    """The escape itself, not just the validation: nothing lands in the parent.

    The manifest is written to disk and read back through ``run()``, so the
    path reaches ``materialize()`` the same way it would in a real delivery --
    which is how the unfixed ordering wrote the file before rejecting it.
    """
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    (delivery / "asset-manifest.json").write_text(
        json.dumps(manifest_declaring(asset("x", "../outside/escaped.txt"))), encoding="utf-8"
    )
    (delivery / "edit-plan.json").write_text(
        json.dumps(plan_referencing("../outside/escaped.txt")), encoding="utf-8"
    )

    with pytest.raises(upstream_handoff.HandoffError):
        upstream_handoff.run(delivery)
    assert not list(tmp_path.glob("outside")), "materialize() wrote outside the delivery root"
    assert not list(tmp_path.rglob("escaped.txt"))


def test_duplicate_asset_ids_are_rejected():
    """An id collision makes a manifest ambiguous for a consumer resolving by id."""
    manifest = manifest_declaring(asset("same", "assets/a.mp4"), asset("same", "assets/b.mp4"))
    with pytest.raises(upstream_handoff.HandoffError, match="repeats the id"):
        upstream_handoff.declared_paths(manifest)


@pytest.mark.skipif(
    not _symlinks_supported(),
    reason="symlinks need developer mode or elevated privileges on this platform",
)
def test_a_symlinked_ancestor_cannot_redirect_a_write_outside_the_root(tmp_path):
    """Containment has to hold at the filesystem level, not only lexically.

    ``assets/escaped.txt`` is lexically inside the root, so every textual check
    passes -- but if ``assets`` is a symlink to a directory outside the root,
    the write lands there instead. resolve_referenced_files() resolves before
    checking containment, which is what closes this.
    """
    delivery = tmp_path / "delivery"
    (delivery / "assets").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (delivery / "link").symlink_to(outside, target_is_directory=True)

    manifest = manifest_declaring(asset("x", "link/escaped.txt"))
    upstream_handoff.declared_paths(manifest)  # lexical check passes -- the point
    with pytest.raises(
        (upstream_handoff.HandoffError, ValueError), match="outside the delivery root"
    ):
        upstream_handoff.materialize(manifest, delivery)
    assert not (outside / "escaped.txt").exists(), "the write escaped the delivery root"


def test_reconcile_rejects_a_declared_file_that_was_never_delivered_even_if_unused(tmp_path):
    """Existence is checked over every declared path, not just referenced ones.

    A declared file that never arrived is a broken delivery. Reporting it as
    merely "unused" would let --no-materialize exit 0 on it.
    """
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "a.mp4").write_bytes(b"")
    # 'a' is delivered and referenced; 'spare' is declared but never arrived.
    with pytest.raises(upstream_handoff.HandoffError, match="every declared file"):
        upstream_handoff.reconcile(
            manifest_declaring(
                asset("a", "assets/a.mp4"), asset("spare", "assets/spare.png", kind="image")
            ),
            plan_referencing("assets/a.mp4"),
            tmp_path,
        )


@pytest.mark.parametrize("bad_root", [None, "somewhere/", "./", "assets"])
def test_delivery_root_must_be_the_manifest_directory(tmp_path, bad_root):
    """delivery_root is required and read, not merely documented.

    Only "." is supported: --media-dir is the delivery root, and honouring a
    second authority for the same paths would mean two answers to "where is
    this file". Anything else is rejected rather than silently ignored.
    """
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    manifest = manifest_declaring(asset("a", "assets/a.mp4"))
    if bad_root is None:
        manifest.pop("delivery_root")
    else:
        manifest["delivery_root"] = bad_root
    (delivery / "asset-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (delivery / "edit-plan.json").write_text(
        json.dumps(plan_referencing("assets/a.mp4")), encoding="utf-8"
    )
    with pytest.raises(upstream_handoff.HandoffError, match="delivery_root"):
        upstream_handoff.run(delivery)


def test_dispatch_refuses_to_run_against_placeholder_media(tmp_path, monkeypatch):
    """Zero-byte placeholders satisfy every existence check but are not footage.

    Assembling them would mutate a real project with fabricated media. The
    bridge must not be reached at all.
    """
    calls: list[tuple] = []
    monkeypatch.setattr(
        upstream_handoff, "_call_bridge", lambda action, params: calls.append((action, params))
    )
    delivery = delivery_copy(tmp_path)
    with pytest.raises(upstream_handoff.HandoffError, match="placeholder media"):
        upstream_handoff.run(delivery, dispatch=True)
    assert calls == [], "dispatch reached the bridge despite placeholder media"


def test_dispatch_refuses_placeholders_left_by_an_earlier_run(tmp_path, monkeypatch):
    """The in-run guard cannot see a placeholder it did not create.

    Placeholders are gitignored, so a previous offline run leaves zero-byte
    media on disk and walks away. The next run finds nothing missing, so it
    creates nothing, ``placeholders_created`` stays empty and
    ``--no-materialize`` has no missing file to report either. Existence checks
    all pass -- the file is declared, present and inside the root -- so only
    the size left to read says it is not footage.
    """
    calls: list[tuple] = []
    monkeypatch.setattr(
        upstream_handoff, "_call_bridge", lambda action, params: calls.append((action, params))
    )

    delivery = delivery_copy(tmp_path)
    # What an interrupted offline run leaves behind: declared, present, empty.
    (delivery / "assets").mkdir()
    for name in ("earthrise.mp4", "oahu_flyover.mp4", "free_ambient.wav"):
        (delivery / "assets" / name).write_bytes(b"")

    # --no-materialize is the operator's ``report it instead`` switch, and it is
    # exactly the one that used to let this through.
    with pytest.raises(upstream_handoff.HandoffError, match="zero bytes"):
        upstream_handoff.run(delivery, dispatch=True, materialize_placeholders=False)
    assert calls == [], "dispatch reached the bridge despite zero-byte media"


def test_a_legitimately_empty_file_is_reported_not_guessed_at(tmp_path):
    """The refusal names the ambiguity instead of silently picking a reading.

    A zero-byte file has two honest explanations and the contract cannot tell
    them apart, so the message has to say both and leave the call to the
    operator. Asserted on the helper so the wording is the contract, not
    collateral of one dispatch path.
    """
    delivery = delivery_copy(tmp_path)
    (delivery / "assets").mkdir()
    (delivery / "assets" / "earthrise.mp4").write_bytes(b"")
    for name in ("oahu_flyover.mp4", "free_ambient.wav"):
        (delivery / "assets" / name).write_bytes(b"real")

    assert upstream_handoff.empty_referenced_files(
        {"tracks": [{"clips": [{"media": "assets/earthrise.mp4"}]}]}, delivery
    ) == ["assets/earthrise.mp4"]

    with pytest.raises(upstream_handoff.HandoffError) as caught:
        upstream_handoff.run(delivery, dispatch=True, materialize_placeholders=False)
    message = str(caught.value)
    assert "placeholder" in message, "the refusal never mentions the placeholder reading"
    assert "legitimately empty" in message, "the refusal never mentions the other reading"


def test_dispatch_payload_carries_media_dir_and_export(tmp_path, monkeypatch):
    """apply_edit_plan requires media_dir whenever dry_run is false.

    Omitting it made stage 6 fail with `media_dir is required unless dry_run is
    true` while the stage table still advertised it as working. This asserts the
    payload shape, with the bridge stubbed so no host is needed.
    """
    calls: list[tuple] = []
    monkeypatch.setattr(
        upstream_handoff,
        "_call_bridge",
        lambda action, params: calls.append((action, params)) or {"ok": True},
    )
    delivery = delivery_copy(tmp_path, with_media=True)

    verdict = upstream_handoff.run(delivery, dispatch=True, export=True)
    assert verdict["stage"] == "complete"

    assert len(calls) == 1
    action, params = calls[0]
    assert action == "apply_edit_plan"
    assert sorted(params) == ["export", "media_dir", "plan", "strategy"]
    assert params["media_dir"] == str(delivery)
    assert params["export"] is True
    assert params["strategy"] == "auto"


def test_a_delivery_with_no_subtitles_completes_the_host_free_stages(tmp_path):
    """compile_plan always emits `subtitles`, and an empty one is rejected on re-entry.

    A delivery that legitimately carries no subtitle files used to crash at the
    OTIO round trip and again at the action script, because normalize_plan()
    insists the field be omitted rather than empty.
    """
    delivery = delivery_copy(tmp_path)
    plan = json.loads((delivery / "edit-plan.json").read_text(encoding="utf-8"))
    plan.pop("subtitles", None)
    (delivery / "edit-plan.json").write_text(json.dumps(plan), encoding="utf-8")

    verdict = upstream_handoff.run(delivery)
    assert verdict["stage"] == "host-free complete"
    assert verdict["plan"]["subtitle_count"] == 0
    assert verdict["action_script"]["step_count"] > 0


def test_reconcile_rejects_a_plan_referencing_an_undeclared_path(tmp_path):
    with pytest.raises(upstream_handoff.HandoffError, match="does not declare"):
        upstream_handoff.reconcile(
            manifest_declaring(asset("a", "assets/a.mp4")),
            plan_referencing("assets/ghost.mp4"),
            tmp_path,
        )


def test_reconcile_rejects_a_declared_file_that_was_never_delivered(tmp_path):
    with pytest.raises(upstream_handoff.HandoffError, match="does not contain every"):
        upstream_handoff.reconcile(
            manifest_declaring(asset("a", "assets/a.mp4")),
            plan_referencing("assets/a.mp4"),
            tmp_path,
        )


def test_reconcile_reports_unused_assets_instead_of_ignoring_them(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "a.mp4").write_bytes(b"")
    (tmp_path / "assets" / "spare.png").write_bytes(b"")
    verdict = upstream_handoff.reconcile(
        manifest_declaring(
            asset("a", "assets/a.mp4"), asset("spare", "assets/spare.png", kind="image")
        ),
        plan_referencing("assets/a.mp4"),
        tmp_path,
    )
    assert verdict["unused"] == ["assets/spare.png"]


def test_cli_rejects_a_delivery_root_that_does_not_exist(tmp_path, capsys):
    assert upstream_handoff.main(["--media-dir", str(tmp_path / "nope")]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_accepts_a_valid_delivery_and_reports_host_free(tmp_path, capsys):
    assert upstream_handoff.main(["--media-dir", str(delivery_copy(tmp_path)), "--json"]) == 0
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["stage"] == "host-free complete"
