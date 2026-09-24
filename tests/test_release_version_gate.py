"""The release version gate has to fail on the drift it was added for.

`tools/check_release_version.py` exists because a wheel built from
`pyproject.toml` and a panel archive built from the release tag could disagree
without anything noticing. These tests pin that failure mode and every cheaper
one around it: a gate that only fails on the case that already happened is one
edit away from being bypassed again.

Artifacts are built here rather than mocked, so a change to the real manifest
or metadata layout breaks a test instead of quietly agreeing with a stale
fixture.
"""

from __future__ import annotations

import importlib.util
import io
import json
import tarfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

_PATH = Path(__file__).parents[1] / "tools" / "check_release_version.py"
_SPEC = importlib.util.spec_from_file_location("check_release_version", _PATH)
assert _SPEC and _SPEC.loader
check_release_version = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_release_version)

check = check_release_version.check
main = check_release_version.main
PYPROJECT = check_release_version.PYPROJECT
VERSION_FILE = check_release_version.VERSION_FILE
label = check_release_version.label
project_version_without_tomllib = check_release_version.project_version_without_tomllib
read_package_version = check_release_version.read_package_version
read_project_version = check_release_version.read_project_version

_PANEL_PATH = Path(__file__).parents[1] / "tools" / "build_panel_archive.py"
_PANEL_SPEC = importlib.util.spec_from_file_location("build_panel_archive", _PANEL_PATH)
assert _PANEL_SPEC and _PANEL_SPEC.loader
build_panel_archive = importlib.util.module_from_spec(_PANEL_SPEC)
_PANEL_SPEC.loader.exec_module(build_panel_archive)

# Not a real release number, so that a grep for version literals cannot mistake
# these fixtures for a stale assertion about the package itself.
VERSION = "1.2.3"
NEWER = "1.3.0"


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Keep problem output on stderr so assertions do not depend on CI."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


def write_sources(directory: Path, version: str = VERSION) -> tuple[Path, Path]:
    """Write a pyproject/`__version__.py` pair that declares ``version``."""
    directory.mkdir(parents=True, exist_ok=True)
    pyproject = directory / "pyproject.toml"
    pyproject.write_text(f'[project]\nname = "dcc-mcp-capcut"\nversion = "{version}"\n')
    version_file = directory / "src" / "dcc_mcp_capcut" / "__version__.py"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(f'__version__ = "{version}"  # x-release-please-version\n')
    return pyproject, version_file


def make_wheel(path: Path, version: str = VERSION, *, metadata_version: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as archive:
        archive.writestr(
            f"dcc_mcp_capcut-{version}.dist-info/METADATA",
            "Metadata-Version: 2.1\n"
            "Name: dcc-mcp-capcut\n"
            f"Version: {metadata_version or version}\n"
            "\n",
        )
    return path


def make_sdist(path: Path, version: str = VERSION, *, pkg_info_version: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (
        f"Metadata-Version: 2.1\nName: dcc-mcp-capcut\nVersion: {pkg_info_version or version}\n\n"
    ).encode()
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo(f"dcc_mcp_capcut-{version}/PKG-INFO")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return path


def make_panel(path: Path, version: str = VERSION) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    build_panel_archive.build(path, version)
    return path


def make_dist(directory: Path, version: str = VERSION) -> Path:
    """Fill ``directory`` with a wheel, an sdist and a panel zip at ``version``."""
    make_wheel(directory / f"dcc_mcp_capcut-{version}-py3-none-any.whl", version)
    make_sdist(directory / f"dcc_mcp_capcut-{version}.tar.gz", version)
    make_panel(directory / f"dcc-mcp-capcut-{version}-panel.zip", version)
    return directory


def test_the_repo_sources_agree_and_look_like_a_version():
    versions, problems = check()
    assert problems == []
    assert set(versions.values()) == {check_release_version.read_package_version(VERSION_FILE)}
    assert all(check_release_version.VERSION_RE.match(v) for v in versions.values())


def test_the_tomllib_fallback_agrees_with_tomllib_on_the_real_pyproject():
    text = PYPROJECT.read_text(encoding="utf-8")
    assert project_version_without_tomllib(text) == read_project_version(PYPROJECT)


def test_the_tomllib_fallback_reads_only_the_project_table():
    text = '[project]\nname = "x"\nversion = "1.2.3"\n\n[tool.other]\nversion = "9.9.9"\n'
    assert project_version_without_tomllib(text) == VERSION


def test_the_tomllib_fallback_finds_nothing_without_a_project_version():
    assert project_version_without_tomllib('[tool.other]\nversion = "9.9.9"\n') is None


def test_the_tomllib_fallback_enters_a_header_that_carries_a_comment():
    # `[project] # release metadata` is valid TOML, and a scan that did not
    # recognise it would leave the gate outside every table on Python 3.9.
    text = '[project] # release metadata\nversion = "1.2.3"\n'
    assert project_version_without_tomllib(text) == VERSION


def test_the_tomllib_fallback_keeps_a_hash_inside_a_quoted_header():
    text = '["a#b"]\nversion = "9.9.9"\n\n[project]\nversion = "1.2.3"\n'
    assert project_version_without_tomllib(text) == VERSION


@pytest.mark.parametrize(
    ("candidate", "accepted"),
    [
        ("0.3.0", True),
        ("1.2.3+local", True),
        ("1.2.3-rc1", True),
        ("1.2.3rc1", False),
        ("1.2.3-", False),
        ("1.2", False),
        ("", False),
    ],
)
def test_only_a_version_a_build_could_have_produced_is_accepted(candidate, accepted):
    assert bool(check_release_version.VERSION_RE.match(candidate)) is accepted


def test_a_pyproject_without_a_project_version_is_a_problem(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "dcc-mcp-capcut"\n')
    with pytest.raises(ValueError, match="project.*version"):
        read_project_version(pyproject)


def test_a_version_module_without_a_version_is_a_problem(tmp_path):
    version_file = tmp_path / "__version__.py"
    version_file.write_text("__version__ = None\n")
    with pytest.raises(ValueError, match="__version__"):
        read_package_version(version_file)


def test_a_matching_set_of_artifacts_passes_the_gate(tmp_path):
    pyproject, version_file = write_sources(tmp_path / "tree")
    dist = make_dist(tmp_path / "dist")

    versions, problems = check(dist, VERSION, pyproject=pyproject, version_file=version_file)
    assert problems == []
    # The gate reads the version out of three artifact kinds, not just the tree.
    assert len(versions) == 5


def test_a_lagging_tree_fails_the_tag_gate(tmp_path):
    """The PIP-3486 case: the tag moved on, pyproject.toml did not."""
    pyproject, version_file = write_sources(tmp_path / "tree", VERSION)
    dist = make_dist(tmp_path / "dist", VERSION)

    _, problems = check(dist, NEWER, pyproject=pyproject, version_file=version_file)

    assert len(problems) == 5
    assert all(f"not the release version {NEWER!r}" in problem for problem in problems)


def test_a_panel_archive_built_from_the_tag_exposes_a_lagging_tree(tmp_path):
    """The mixed release, reproduced: only the panel followed the tag."""
    pyproject, version_file = write_sources(tmp_path / "tree", VERSION)
    dist = tmp_path / "dist"
    make_wheel(dist / f"dcc_mcp_capcut-{VERSION}-py3-none-any.whl", VERSION)
    make_sdist(dist / f"dcc_mcp_capcut-{VERSION}.tar.gz", VERSION)
    make_panel(dist / f"dcc-mcp-capcut-{NEWER}-panel.zip", NEWER)

    versions, problems = check(dist, NEWER, pyproject=pyproject, version_file=version_file)

    assert versions[f"dcc-mcp-capcut-{NEWER}-panel.zip"] == NEWER
    assert [problem for problem in problems if "panel.zip" in problem] == []
    assert any("pyproject.toml" in problem for problem in problems)
    assert any(
        problem.endswith(f"declares {VERSION!r}, not the release version {NEWER!r}")
        for problem in problems
    )


def test_artifacts_must_agree_even_without_an_expected_version(tmp_path):
    pyproject, version_file = write_sources(tmp_path / "tree", VERSION)
    dist = tmp_path / "dist"
    make_wheel(dist / f"dcc_mcp_capcut-{VERSION}-py3-none-any.whl", VERSION)
    make_sdist(dist / f"dcc_mcp_capcut-{NEWER}.tar.gz", NEWER)

    _, problems = check(dist, pyproject=pyproject, version_file=version_file)

    assert len(problems) == 1
    assert problems[0].startswith("artifacts disagree on the version:")
    assert f"{VERSION!r}" in problems[0] and f"{NEWER!r}" in problems[0]


def test_a_wheel_whose_filename_disagrees_with_its_metadata_is_rejected(tmp_path):
    path = make_wheel(
        tmp_path / f"dcc_mcp_capcut-{VERSION}-py3-none-any.whl", VERSION, metadata_version=NEWER
    )
    _, problems = check(pyproject=PYPROJECT, version_file=VERSION_FILE, dist=path.parent)
    assert any("METADATA says" in problem for problem in problems)


def test_an_sdist_whose_filename_disagrees_with_its_pkg_info_is_rejected(tmp_path):
    make_sdist(tmp_path / f"dcc_mcp_capcut-{VERSION}.tar.gz", VERSION, pkg_info_version=NEWER)
    _, problems = check(pyproject=PYPROJECT, version_file=VERSION_FILE, dist=tmp_path)
    assert any("PKG-INFO says" in problem for problem in problems)


def test_a_panel_archive_renamed_to_another_version_is_rejected(tmp_path):
    built = make_panel(tmp_path / f"dcc-mcp-capcut-{VERSION}-panel.zip", VERSION)
    built.rename(tmp_path / f"dcc-mcp-capcut-{NEWER}-panel.zip")
    _, problems = check(pyproject=PYPROJECT, version_file=VERSION_FILE, dist=tmp_path)
    assert any("manifest says" in problem for problem in problems)


def test_an_artifact_the_gate_cannot_version_is_rejected(tmp_path):
    """Fail closed: an unreadable upload is not a version nobody checked."""
    (tmp_path / "notes.txt").write_text("release notes\n")
    _, problems = check(pyproject=PYPROJECT, version_file=VERSION_FILE, dist=tmp_path)
    assert any("not a versioned release artifact" in problem for problem in problems)


def test_an_empty_dist_directory_is_rejected(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    _, problems = check(pyproject=PYPROJECT, version_file=VERSION_FILE, dist=dist)
    assert any("no artifacts found" in problem for problem in problems)


def test_a_missing_dist_directory_is_rejected(tmp_path):
    _, problems = check(pyproject=PYPROJECT, version_file=VERSION_FILE, dist=tmp_path / "absent")
    assert any("not a directory" in problem for problem in problems)


def test_a_wheel_without_metadata_is_rejected(tmp_path):
    path = tmp_path / f"dcc_mcp_capcut-{VERSION}-py3-none-any.whl"
    with ZipFile(path, "w") as archive:
        archive.writestr("dcc_mcp_capcut/__init__.py", "")
    _, problems = check(pyproject=PYPROJECT, version_file=VERSION_FILE, dist=tmp_path)
    assert any("expected exactly 1" in problem for problem in problems)


def test_a_wheel_with_two_metadata_members_is_rejected(tmp_path):
    """Two METADATA members mean no single version; guessing one would hide it."""
    path = tmp_path / f"dcc_mcp_capcut-{VERSION}-py3-none-any.whl"
    with ZipFile(path, "w") as archive:
        for version in (VERSION, NEWER):
            archive.writestr(
                f"dcc_mcp_capcut-{version}.dist-info/METADATA",
                f"Metadata-Version: 2.1\nName: dcc-mcp-capcut\nVersion: {version}\n\n",
            )
    _, problems = check(pyproject=PYPROJECT, version_file=VERSION_FILE, dist=tmp_path)
    assert any("holds 2" in problem for problem in problems)


def test_a_panel_archive_without_a_manifest_is_rejected(tmp_path):
    path = tmp_path / f"dcc-mcp-capcut-{VERSION}-panel.zip"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("panel/panel.js", "console.log(1)")
    _, problems = check(pyproject=PYPROJECT, version_file=VERSION_FILE, dist=tmp_path)
    assert any("no manifest.json" in problem for problem in problems)


def test_a_panel_manifest_without_a_version_is_rejected(tmp_path):
    path = tmp_path / f"dcc-mcp-capcut-{VERSION}-panel.zip"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps({"adapter": "capcut"}))
    _, problems = check(pyproject=PYPROJECT, version_file=VERSION_FILE, dist=tmp_path)
    assert any("records no version" in problem for problem in problems)


def test_a_value_that_is_not_a_version_is_reported_as_such(tmp_path):
    pyproject, version_file = write_sources(tmp_path / "tree", "not-a-version")
    _, problems = check(expect=VERSION, pyproject=pyproject, version_file=version_file)
    assert len(problems) == 2
    assert all("is not a version" in problem for problem in problems)


def test_main_accepts_the_repo_at_its_own_version():
    version = read_project_version(PYPROJECT)
    assert main(["--expect", version]) == 0


def test_main_reports_every_problem_and_fails(tmp_path, capsys):
    pyproject, version_file = write_sources(tmp_path / "tree", VERSION)
    make_dist(tmp_path / "dist", VERSION)

    exit_code = main(
        [
            "--expect",
            NEWER,
            "--dist",
            str(tmp_path / "dist"),
            "--pyproject",
            str(pyproject),
            "--version-file",
            str(version_file),
        ]
    )

    assert exit_code == 1
    problems = capsys.readouterr().err.strip().splitlines()
    assert len(problems) == 5
    assert all(NEWER in problem for problem in problems)


def test_main_annotates_problems_on_github_actions(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    pyproject, version_file = write_sources(tmp_path / "tree", VERSION)
    assert (
        main(
            ["--expect", NEWER, "--pyproject", str(pyproject), "--version-file", str(version_file)]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.err.count("::error::") == 2
    # stdout is reserved for --print-version; annotations must not leak into it.
    assert captured.out == ""


def test_github_annotations_never_pollute_print_version(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    pyproject, version_file = write_sources(tmp_path / "tree", VERSION)
    version_file.write_text(f'__version__ = "{NEWER}"\n')
    assert (
        main(
            ["--print-version", "--pyproject", str(pyproject), "--version-file", str(version_file)]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "::error::" in captured.err


def test_print_version_reads_the_source_of_truth(tmp_path, capsys):
    pyproject, version_file = write_sources(tmp_path / "tree", VERSION)
    assert (
        main(
            ["--print-version", "--pyproject", str(pyproject), "--version-file", str(version_file)]
        )
        == 0
    )
    assert capsys.readouterr().out.strip() == VERSION


def test_print_version_stays_silent_when_the_sources_disagree(tmp_path, capsys):
    pyproject, version_file = write_sources(tmp_path / "tree", VERSION)
    version_file.write_text(f'__version__ = "{NEWER}"\n')
    assert (
        main(
            ["--print-version", "--pyproject", str(pyproject), "--version-file", str(version_file)]
        )
        == 1
    )
    assert capsys.readouterr().out == ""


def test_the_gate_labels_a_file_by_the_name_a_reader_would_see(tmp_path):
    assert label(tmp_path / "dcc_mcp_capcut-1.2.3-py3-none-any.whl") == (
        "dcc_mcp_capcut-1.2.3-py3-none-any.whl"
    )
