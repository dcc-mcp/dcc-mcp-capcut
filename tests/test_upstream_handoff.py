"""The upstream handoff format is a promise to a system we do not control.

An upstream generator reads ``references/upstream-handoff.md`` and copies
``demo/upstream-delivery/``. Both rot silently: the document can describe a
manifest the example no longer produces, and the example can stop running while
the document still says it does.

These tests hold the promise:

- the reference document ships inside the package, where an agent can read it;
- the boundary statement stays aligned with ``host-boundary.md`` on the
  specific claims that matter to an upstream caller;
- the worked example actually runs end to end, host-free, on this platform.
"""

from __future__ import annotations

import json
import shutil
from importlib.resources import files
from pathlib import Path

import pytest

from demo import upstream_handoff

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "demo" / "upstream-delivery"
REFERENCES = ROOT / "src" / "dcc_mcp_capcut" / "skills" / "references"

# Claims the two documents must agree on. Each is a phrase both files actually
# carry today; an upstream caller reads only the handoff document, so it has to
# restate the boundary rather than point at host-boundary.md.
ALIGNED_BOUNDARY_CLAIMS = (
    "closed-source",
    "redistribut",
    "consent-gated",
    "loopback",
)


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


def make_delivery(tmp_path: Path) -> Path:
    """Copy the worked example into a scratch root so runs never write into the repo."""
    delivery = tmp_path / "delivery"
    shutil.copytree(EXAMPLE, delivery)
    return delivery


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
    for asset in manifest["assets"]:
        for field in ("id", "path", "kind", "license"):
            assert asset.get(field), f"asset {asset.get('id')!r} is missing {field!r}"
        # attribution/source are optional but must be present-and-null rather
        # than absent, so "nothing owed" is distinguishable from "unchecked".
        for field in ("attribution", "source"):
            assert field in asset, f"asset {asset['id']!r} omits {field!r} instead of nulling it"


def test_example_runs_end_to_end_host_free(tmp_path):
    """Stages 1-5 must run on any platform, including a CI runner with no host.

    This is the guard that keeps the example from becoming pseudocode: it is
    executed, not just present.
    """
    verdict = upstream_handoff.run(make_delivery(tmp_path), dispatch=False)
    assert verdict["stage"] == "host-free complete"
    assert verdict["action_script"]["dispatched"] is False
    assert verdict["action_script"]["step_count"] > 0
    assert verdict["interchange"]["matches_duration"] is True
    # Nothing was dispatched, so no CapCut window was ever required.
    assert "dispatch" not in verdict


def test_reconcile_rejects_a_plan_referencing_an_undeclared_path(tmp_path):
    manifest = {
        "schema": upstream_handoff.MANIFEST_SCHEMA,
        "delivery_root": ".",
        "assets": [
            {
                "id": "a",
                "path": "assets/a.mp4",
                "kind": "video",
                "license": "none",
                "attribution": None,
                "source": None,
            }
        ],
    }
    plan = {
        "schema": upstream_handoff.PLAN_SCHEMA,
        "name": "undeclared",
        "fps": 30,
        "width": 1920,
        "height": 1080,
        "tracks": [
            {
                "name": "V1",
                "kind": "Video",
                "clips": [
                    {
                        "name": "ghost",
                        "media": "assets/ghost.mp4",
                        "start": 0,
                        "duration": 30,
                        "media_duration": 30,
                    }
                ],
            }
        ],
    }
    with pytest.raises(upstream_handoff.HandoffError, match="does not declare"):
        upstream_handoff.reconcile(manifest, plan, tmp_path)


def test_reconcile_rejects_a_declared_file_that_was_never_delivered(tmp_path):
    manifest = {
        "schema": upstream_handoff.MANIFEST_SCHEMA,
        "delivery_root": ".",
        "assets": [
            {
                "id": "a",
                "path": "assets/a.mp4",
                "kind": "video",
                "license": "none",
                "attribution": None,
                "source": None,
            }
        ],
    }
    plan = {
        "schema": upstream_handoff.PLAN_SCHEMA,
        "name": "missing",
        "fps": 30,
        "width": 1920,
        "height": 1080,
        "tracks": [
            {
                "name": "V1",
                "kind": "Video",
                "clips": [
                    {
                        "name": "a",
                        "media": "assets/a.mp4",
                        "start": 0,
                        "duration": 30,
                        "media_duration": 30,
                    }
                ],
            }
        ],
    }
    with pytest.raises(upstream_handoff.HandoffError, match="does not contain every"):
        upstream_handoff.reconcile(manifest, plan, tmp_path)


def test_reconcile_reports_unused_assets_instead_of_ignoring_them(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "a.mp4").write_bytes(b"")
    manifest = {
        "schema": upstream_handoff.MANIFEST_SCHEMA,
        "delivery_root": ".",
        "assets": [
            {
                "id": "a",
                "path": "assets/a.mp4",
                "kind": "video",
                "license": "none",
                "attribution": None,
                "source": None,
            },
            {
                "id": "spare",
                "path": "assets/spare.png",
                "kind": "image",
                "license": "none",
                "attribution": None,
                "source": None,
            },
        ],
    }
    plan = {
        "schema": upstream_handoff.PLAN_SCHEMA,
        "name": "spare",
        "fps": 30,
        "width": 1920,
        "height": 1080,
        "tracks": [
            {
                "name": "V1",
                "kind": "Video",
                "clips": [
                    {
                        "name": "a",
                        "media": "assets/a.mp4",
                        "start": 0,
                        "duration": 30,
                        "media_duration": 30,
                    }
                ],
            }
        ],
    }
    (tmp_path / "assets" / "spare.png").write_bytes(b"")
    verdict = upstream_handoff.reconcile(manifest, plan, tmp_path)
    assert verdict["unused"] == ["assets/spare.png"]


def test_cli_rejects_a_delivery_root_that_does_not_exist(tmp_path, capsys):
    assert upstream_handoff.main(["--media-dir", str(tmp_path / "nope")]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_accepts_a_valid_delivery_and_reports_host_free(tmp_path, capsys):
    assert upstream_handoff.main(["--media-dir", str(make_delivery(tmp_path)), "--json"]) == 0
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["stage"] == "host-free complete"
