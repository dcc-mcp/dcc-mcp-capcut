"""Shipped skill documentation must stay complete, consistent and packaged.

These tests guard the contract an agent consumes: every bundled skill carries a
real body, the frontmatter stays machine-readable and stable, the shared
references ship inside the package, and every relative link in a skill body
resolves. They run against the source tree and, where noted, through the
imported package.
"""

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SKILLS = ROOT / "src" / "dcc_mcp_capcut" / "skills"
REFERENCES = SKILLS / "references"

SKILL_DIRS = sorted(path for path in SKILLS.glob("capcut-*") if path.is_dir())

# Host-backed skills dispatch through the loopback bridge, so their bodies must
# document the panel-timeout failure mode. These two deliberately do not.
NON_BRIDGE_SKILLS = {"capcut-interchange", "capcut-native"}

REQUIRED_SECTIONS = ("## Prerequisites", "## Failure recovery", "## Acceptance", "## Boundaries")

REFERENCE_FILES = (
    "dependencies-and-notices.md",
    "export-and-verification.md",
    "host-boundary.md",
    "host-platforms.md",
    "troubleshooting.md",
)

FRONTMATTER_KEYS = {"name", "description", "license", "compatibility", "allowed-tools", "metadata"}

BRIDGE_TIMEOUT_MESSAGE = "CapCut bridge did not respond; open the bundled panel"


def parse_frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.DOTALL)
    assert match, f"{path.name} must start with a fenced YAML frontmatter block"
    return yaml.safe_load(match.group(1)), match.group(2)


def test_every_skill_directory_was_discovered():
    assert [path.name for path in SKILL_DIRS] == [
        "capcut-ai",
        "capcut-assemble",
        "capcut-audio",
        "capcut-effects",
        "capcut-export",
        "capcut-interchange",
        "capcut-media",
        "capcut-native",
        "capcut-project",
        "capcut-setup",
        "capcut-text",
        "capcut-timeline",
    ]


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda path: path.name)
def test_skill_body_is_not_empty(skill_dir):
    _, body = parse_frontmatter(skill_dir / "SKILL.md")
    meaningful = [line for line in body.splitlines() if line.strip()]
    assert meaningful, f"{skill_dir.name}/SKILL.md has an empty body"
    assert len(meaningful) >= 15, f"{skill_dir.name}/SKILL.md body is too thin to be useful"


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda path: path.name)
def test_frontmatter_stays_stable_and_machine_readable(skill_dir):
    frontmatter, _ = parse_frontmatter(skill_dir / "SKILL.md")
    assert set(frontmatter) == FRONTMATTER_KEYS
    assert frontmatter["name"] == skill_dir.name
    assert frontmatter["license"] == "MIT"
    assert frontmatter["allowed-tools"] == "Python"
    assert frontmatter["description"].strip()
    assert frontmatter["compatibility"].strip()

    metadata = frontmatter["metadata"]["dcc-mcp"]
    assert metadata["dcc"] == "capcut"
    assert metadata["version"] == "0.1.0"
    assert metadata["layer"] in {"domain", "infrastructure"}
    assert metadata["stage"] in {"setup", "scene", "delivery"}
    assert isinstance(metadata["tags"], str) and metadata["tags"]
    assert metadata["tools"] == "tools.yaml"
    assert (skill_dir / metadata["tools"]).is_file()


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda path: path.name)
def test_body_covers_the_operating_contract(skill_dir):
    _, body = parse_frontmatter(skill_dir / "SKILL.md")
    for section in REQUIRED_SECTIONS:
        assert section in body, f"{skill_dir.name}/SKILL.md is missing {section!r}"
    if skill_dir.name not in NON_BRIDGE_SKILLS:
        assert BRIDGE_TIMEOUT_MESSAGE in body, (
            f"{skill_dir.name}/SKILL.md must document the bridge timeout failure mode"
        )


@pytest.mark.parametrize("name", REFERENCE_FILES)
def test_shared_references_exist_and_are_packaged(name):
    source = REFERENCES / name
    assert source.is_file()
    text = source.read_text(encoding="utf-8")
    assert len(text.splitlines()) >= 20, f"{name} is too thin to be useful"

    # The same file must be reachable through the installed package, which is
    # what an agent actually consumes.
    from importlib.resources import files

    packaged = files("dcc_mcp_capcut").joinpath(f"skills/references/{name}")
    assert packaged.is_file()
    assert packaged.read_text(encoding="utf-8") == text


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda path: path.name)
def test_relative_reference_links_resolve(skill_dir):
    _, body = parse_frontmatter(skill_dir / "SKILL.md")
    targets = re.findall(r"\]\((\.\./references/[^)]+)\)", body)
    assert targets, f"{skill_dir.name}/SKILL.md links no shared reference"
    for target in targets:
        assert (skill_dir / target).is_file(), f"{skill_dir.name}/SKILL.md links a missing {target}"


def test_root_skill_is_an_index_outside_the_lint_loop():
    frontmatter, body = parse_frontmatter(ROOT / "SKILL.md")
    assert frontmatter["name"] == "dcc-mcp-capcut"
    # The index carries no per-release version and no tool catalog: it is a
    # router, and the lint glob must stay pointed at skills/capcut-*.
    assert "version" not in frontmatter["metadata"]["dcc-mcp"]
    assert "tools" not in frontmatter["metadata"]["dcc-mcp"]
    assert "not in the lint loop" in body

    for skill_dir in SKILL_DIRS:
        assert f"`{skill_dir.name}`" in body, f"root SKILL.md does not index {skill_dir.name}"


def test_release_please_bumps_every_packaged_skill():
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    extra_files = config["packages"]["."]["extra-files"]
    for skill_dir in SKILL_DIRS:
        relative = f"src/dcc_mcp_capcut/skills/{skill_dir.name}/SKILL.md"
        assert relative in extra_files, f"{relative} would keep a stale version after a release"
