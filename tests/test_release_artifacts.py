"""The panel release archive must be verifiable, not merely documented.

`tools/build_panel_archive.py` records a SHA-256 per payload member. These tests
hold the two halves together: the recorded digests describe the bytes that were
actually archived, and `--verify` rejects an artifact whose bytes no longer match
its manifest. Digests are the point of the manifest, so a recorded-but-wrong
digest has to fail here rather than at install time on an operator's machine.
"""

import importlib.util
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

_PATH = Path(__file__).parents[1] / "tools" / "build_panel_archive.py"
_SPEC = importlib.util.spec_from_file_location("build_panel_archive", _PATH)
assert _SPEC and _SPEC.loader
build_panel_archive = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_panel_archive)

FILES = build_panel_archive.FILES
MANIFEST_NAME = build_panel_archive.MANIFEST_NAME
PANEL_PREFIX = build_panel_archive.PANEL_PREFIX
build = build_panel_archive.build
sha256_hex = build_panel_archive.sha256_hex
verify_archive = build_panel_archive.verify_archive

PANEL_MEMBERS = sorted(f"{PANEL_PREFIX}/{name}" for name in FILES)

# The archive version is an input to the builder, not this package's version:
# the builder records whatever it is handed and never compares it to the
# package. It is deliberately not a real release number so that a grep for
# version literals cannot mistake it for a stale assertion about the package.
SYNTHETIC_VERSION = "9.9.9"

HOST_ACCEPTANCE = {
    "architecture": "x86_64",
    "compiler_abi": "msvc-14.3",
    "qt_version": "6.2.2",
    "host": "CapCut 9.4.0.4015",
    "evidence": "tools/test_qt_probe_native.py on the 9.4.0.4015 host",
}


def read_manifest(archive_path: Path) -> dict:
    with ZipFile(archive_path) as archive:
        return json.loads(archive.read(MANIFEST_NAME))


def test_panel_archive_is_deterministic_and_versioned(tmp_path):
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    build(first, SYNTHETIC_VERSION)
    build(second, SYNTHETIC_VERSION)

    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        manifest = json.loads(archive.read(MANIFEST_NAME))
        # The pre-hash contract stays intact for existing consumers.
        assert manifest["adapter"] == "capcut"
        assert manifest["version"] == SYNTHETIC_VERSION
        assert manifest["files"] == list(FILES)
        assert set(archive.namelist()) == {MANIFEST_NAME, *PANEL_MEMBERS}


def test_sha256_hex_matches_a_known_answer():
    """A wrong-but-self-consistent hash would pass every round-trip assertion.

    The manifest tests compare `sha256_hex` against itself, so they cannot tell
    a correct digest from a stable one. Published digests are the contract, and
    a consumer hashes with a real SHA-256 implementation, so pin known answers.
    """
    assert sha256_hex(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert sha256_hex(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_manifest_digests_match_the_archived_bytes(tmp_path):
    archive_path = tmp_path / "panel.zip"
    build(archive_path, SYNTHETIC_VERSION)

    manifest = read_manifest(archive_path)
    assert sorted(manifest["files_sha256"]) == PANEL_MEMBERS

    with ZipFile(archive_path) as archive:
        for member, digest in manifest["files_sha256"].items():
            assert digest == sha256_hex(archive.read(member))
            assert digest == digest.lower() and len(digest) == 64


def test_manifest_digests_track_panel_content(tmp_path, monkeypatch):
    """A digest must describe the real panel source, not a constant."""
    archive_path = tmp_path / "panel.zip"
    panel = (
        Path(build_panel_archive.__file__).parents[1] / "src" / "dcc_mcp_capcut" / "capcut_panel"
    )
    original = (panel / FILES[0]).read_bytes()

    monkeypatch.setattr(
        build_panel_archive,
        "panel_payloads",
        lambda _panel: {f"{PANEL_PREFIX}/{name}": b"tampered" for name in FILES},
    )
    build(archive_path, SYNTHETIC_VERSION)
    tampered = read_manifest(archive_path)["files_sha256"]

    monkeypatch.setattr(
        build_panel_archive,
        "panel_payloads",
        lambda _panel: {f"{PANEL_PREFIX}/{name}": original for name in FILES},
    )
    build(archive_path, SYNTHETIC_VERSION)
    restored = read_manifest(archive_path)["files_sha256"]

    assert tampered[f"{PANEL_PREFIX}/{FILES[0]}"] != restored[f"{PANEL_PREFIX}/{FILES[0]}"]


def test_host_acceptance_is_omitted_until_a_host_build_supplies_it(tmp_path):
    archive_path = tmp_path / "panel.zip"
    build(archive_path, SYNTHETIC_VERSION)
    assert "host_acceptance" not in read_manifest(archive_path)


def test_host_acceptance_is_embedded_when_supplied(tmp_path):
    archive_path = tmp_path / "panel.zip"
    build(archive_path, SYNTHETIC_VERSION, HOST_ACCEPTANCE)
    assert read_manifest(archive_path)["host_acceptance"] == HOST_ACCEPTANCE


@pytest.mark.parametrize("host_acceptance", [None, HOST_ACCEPTANCE])
def test_verify_accepts_a_freshly_built_archive(tmp_path, host_acceptance):
    archive_path = tmp_path / "panel.zip"
    build(archive_path, SYNTHETIC_VERSION, host_acceptance)
    assert verify_archive(archive_path) == []


def test_verify_rejects_a_tampered_member(tmp_path):
    archive_path = tmp_path / "panel.zip"
    build(archive_path, SYNTHETIC_VERSION)
    member = f"{PANEL_PREFIX}/{FILES[0]}"

    with ZipFile(archive_path) as source:
        members = {name: source.read(name) for name in source.namelist()}
    members[member] = members[member] + b"/* tampered */"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as target:
        for name, data in members.items():
            target.writestr(name, data)

    problems = verify_archive(archive_path)
    assert any("digest mismatch" in problem and member in problem for problem in problems)


def test_verify_rejects_a_member_missing_from_the_archive(tmp_path):
    archive_path = tmp_path / "panel.zip"
    build(archive_path, SYNTHETIC_VERSION)
    member = f"{PANEL_PREFIX}/{FILES[0]}"

    with ZipFile(archive_path) as source:
        members = {name: source.read(name) for name in source.namelist()}
    del members[member]
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as target:
        for name, data in members.items():
            target.writestr(name, data)

    problems = verify_archive(archive_path)
    assert any("missing from the archive" in problem and member in problem for problem in problems)


def test_verify_flags_an_archive_without_digests(tmp_path):
    archive_path = tmp_path / "panel.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            MANIFEST_NAME, json.dumps({"adapter": "capcut", "version": SYNTHETIC_VERSION})
        )
    problems = verify_archive(archive_path)
    assert any("no files_sha256 digests" in problem for problem in problems)


def test_verify_flags_a_payload_with_no_recorded_digest(tmp_path):
    archive_path = tmp_path / "panel.zip"
    build(archive_path, SYNTHETIC_VERSION)

    with ZipFile(archive_path) as source:
        members = {name: source.read(name) for name in source.namelist()}
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as target:
        for name, data in members.items():
            target.writestr(name, data)
        target.writestr(f"{PANEL_PREFIX}/extra.js", b"// unrecorded")

    problems = verify_archive(archive_path)
    assert any("extra.js" in problem and "no recorded digest" in problem for problem in problems)


def test_verify_rejects_duplicate_members(tmp_path):
    """A repeated name is malformed, even when the winning copy is intact.

    Readers resolve a repeated name to the entry written last, so verifying
    only that copy would leave an archive that checks out here but extracts
    different bytes for a consumer. Malformed wins over "the last one matches".
    """
    archive_path = tmp_path / "panel.zip"
    build(archive_path, SYNTHETIC_VERSION)
    member = f"{PANEL_PREFIX}/{FILES[0]}"

    with ZipFile(archive_path) as source:
        members = {name: source.read(name) for name in source.namelist()}
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as target:
        for name, data in members.items():
            target.writestr(name, data)
        # Append a second copy with different bytes; the manifest digest still
        # matches whichever copy the reader happens to resolve.
        target.writestr(member, b"console.log('tampered duplicate')")

    problems = verify_archive(archive_path)
    assert any("appears more than once" in problem and member in problem for problem in problems)


def test_verify_reports_a_missing_manifest(tmp_path):
    archive_path = tmp_path / "panel.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(f"{PANEL_PREFIX}/{FILES[0]}", b"console.log(1)")
    assert verify_archive(archive_path) == [f"{MANIFEST_NAME} is missing from the archive"]


def test_cli_verify_returns_a_nonzero_exit_code(tmp_path, capsys):
    archive_path = tmp_path / "panel.zip"
    build(archive_path, SYNTHETIC_VERSION)
    assert build_panel_archive.main(["--verify", str(archive_path)]) == 0
    assert "ok" in capsys.readouterr().out

    with ZipFile(archive_path) as source:
        members = {name: source.read(name) for name in source.namelist()}
    members[f"{PANEL_PREFIX}/{FILES[0]}"] = b"tampered"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as target:
        for name, data in members.items():
            target.writestr(name, data)

    assert build_panel_archive.main(["--verify", str(archive_path)]) == 1


def test_cli_build_requires_output_and_version():
    with pytest.raises(SystemExit):
        build_panel_archive.main(["--version", SYNTHETIC_VERSION])
