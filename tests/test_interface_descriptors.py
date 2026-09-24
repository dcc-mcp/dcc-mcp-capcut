"""The agent interface descriptor is a shipped surface, so it is guarded.

Every bundled skill carries ``agents/openai.yaml``: the ``interface`` block an
agent UI reads to answer "what is this and what do I send it". It is consumed
by a different reader than ``SKILL.md``, which is exactly why it can drift.

These tests hold the two surfaces together:

- one descriptor per skill, and none anywhere else;
- the descriptor describes the same capability the frontmatter does, rather
  than becoming a second opinion;
- the descriptor ships inside the package, because that is the copy an agent
  reads.

The consistency check is a one-way subset test. Every significant word of
``short_description`` must appear in the frontmatter ``description``. A
descriptor may shorten the frontmatter -- it is a picker label -- but it may
not introduce a capability the frontmatter never claims, and it may not swap in
a synonym that silently narrows the skill.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SKILLS = ROOT / "src" / "dcc_mcp_capcut" / "skills"

SKILL_DIRS = sorted(path for path in SKILLS.glob("capcut-*") if path.is_dir())

DESCRIPTOR_NAME = "agents/openai.yaml"

INTERFACE_KEYS = {"display_name", "short_description", "default_prompt"}

# A picker label, not a sentence: long enough to identify the skill, short
# enough to render whole in a list.
SHORT_DESCRIPTION_MAX = 64

# A default prompt has to be something an agent can act on, not just the skill
# name restated.
DEFAULT_PROMPT_MIN = 40


def parse_frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.DOTALL)
    assert match, f"{path.name} must start with a fenced YAML frontmatter block"
    return yaml.safe_load(match.group(1)), match.group(2)


def load_descriptor(skill_dir: Path) -> dict:
    """Read the descriptor and assert its shape, so each test checks one thing."""
    path = skill_dir / DESCRIPTOR_NAME
    assert path.is_file(), f"{skill_dir.name} ships no {DESCRIPTOR_NAME}"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"{path} must hold a YAML mapping"
    assert set(document) == {"interface"}, f"{path} must hold exactly one 'interface' key"
    interface = document["interface"]
    assert isinstance(interface, dict), f"{path}: 'interface' must be a mapping"
    assert set(interface) == INTERFACE_KEYS, f"{path}: 'interface' must hold {INTERFACE_KEYS}"
    for key in sorted(INTERFACE_KEYS):
        assert isinstance(interface[key], str) and interface[key].strip(), (
            f"{skill_dir.name}: interface.{key} must be a non-empty string"
        )
    return interface


def significant_words(text: str) -> set[str]:
    """Lowercased words that carry a capability claim, punctuation aside.

    Words of four letters or more always count. Shorter tokens count only when
    they are written as an acronym in the source: ``SRT``, ``EDL`` and ``API``
    are capability claims, while ``and``, ``the`` and ``for`` are not. That is
    why a bare length floor is not enough -- a three-letter acronym would sail
    straight through and let a descriptor advertise a capability the
    frontmatter never states.
    """
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z]+", text)
        if len(token) >= 4 or token.isupper()
    }


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda path: path.name)
def test_every_skill_ships_a_descriptor(skill_dir):
    load_descriptor(skill_dir)


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda path: path.name)
def test_short_description_fits_a_picker(skill_dir):
    short = load_descriptor(skill_dir)["short_description"]
    assert len(short) <= SHORT_DESCRIPTION_MAX, (
        f"{skill_dir.name}: short_description is {len(short)} chars, "
        f"over the {SHORT_DESCRIPTION_MAX}-char picker limit"
    )


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda path: path.name)
def test_default_prompt_is_actionable(skill_dir):
    prompt = load_descriptor(skill_dir)["default_prompt"]
    assert len(prompt) >= DEFAULT_PROMPT_MIN, (
        f"{skill_dir.name}: default_prompt is {len(prompt)} chars, "
        f"under the {DEFAULT_PROMPT_MIN}-char floor -- it must tell an agent what to do"
    )


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda path: path.name)
def test_short_description_claims_nothing_new(skill_dir):
    """The descriptor may shorten the frontmatter, never out-claim it.

    A one-way subset test rather than equality: strict equality would force the
    label to repeat the whole description, and comparing nothing at all is how
    two surfaces drift apart. Subset is the narrowest rule that catches both
    failure modes -- a descriptor advertising capability the skill does not
    have, and one describing a different skill entirely.
    """
    interface = load_descriptor(skill_dir)
    frontmatter, _ = parse_frontmatter(skill_dir / "SKILL.md")
    allowed = significant_words(frontmatter["description"])
    introduced = significant_words(interface["short_description"]) - allowed
    assert not introduced, (
        f"{skill_dir.name}: short_description introduces {sorted(introduced)}, "
        "which the SKILL.md description never claims"
    )


@pytest.mark.parametrize("acronym", ["SRT", "EDL", "API", "XML"])
def test_short_acronyms_are_held_to_the_same_subset_rule(acronym):
    """A three-letter acronym is a capability claim, not boilerplate.

    Guards the guard: the subset check keeps words of four letters or more, so
    an acronym short enough to dodge that floor would otherwise let a
    descriptor advertise something the frontmatter never mentions.
    """
    frontmatter = "Add styled text and captions to the timeline."
    descriptor = f"Edit {acronym} files on the timeline"
    assert acronym.lower() in significant_words(descriptor)
    assert significant_words(descriptor) - significant_words(frontmatter)


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda path: path.name)
def test_display_name_is_a_label_not_a_sentence(skill_dir):
    display_name = load_descriptor(skill_dir)["display_name"]
    assert len(display_name) <= 40, f"{skill_dir.name}: display name will not fit a picker row"
    assert not display_name.endswith("."), f"{skill_dir.name}: a label does not end in a period"


def test_descriptors_ship_inside_the_package():
    """The wheel copy is the one an agent reads, so it has to match the source."""
    from importlib.resources import files

    packaged = files("dcc_mcp_capcut").joinpath("skills")
    for skill_dir in SKILL_DIRS:
        source = skill_dir / DESCRIPTOR_NAME
        shipped = packaged.joinpath(f"{skill_dir.name}/{DESCRIPTOR_NAME}")
        assert shipped.is_file(), f"{DESCRIPTOR_NAME} is missing from the installed package"
        assert shipped.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_no_descriptor_lives_outside_a_skill_directory():
    """A stray descriptor would look like a skill to a picker that scans by file."""
    expected = sorted(f"{skill_dir.name}/{DESCRIPTOR_NAME}" for skill_dir in SKILL_DIRS)
    found = sorted("/".join(path.relative_to(SKILLS).parts) for path in SKILLS.rglob("openai.yaml"))
    assert found == expected
