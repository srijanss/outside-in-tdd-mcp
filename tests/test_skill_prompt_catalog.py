"""core.skill_prompts turns a directory of <name>/SKILL.md skills into MCP
prompts: frontmatter for the listing, the body for prompts/get."""

import pytest

from core.skill_prompts import skill_prompt, skill_prompts


def skill(root, name, description, body):
    (root / name).mkdir(parents=True)
    (root / name / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"
    )


def test_each_skill_is_listed_with_its_frontmatter_description(tmp_path):
    skill(tmp_path, "tdd-start", "Start a feature", "Call init_feature.\n")
    skill(tmp_path, "catch-up", "Reorient a session", "Call session_start.\n")

    listed = skill_prompts(tmp_path)

    assert [(p.name, p.description) for p in listed] == [
        ("catch-up", "Reorient a session"),
        ("tdd-start", "Start a feature"),
    ]
    assert [(a.name, a.required) for a in listed[0].arguments] == [("arguments", False)]


def test_a_skill_is_served_as_its_body_plus_the_given_arguments(tmp_path):
    skill(tmp_path, "tdd-start", "Start a feature", "Call init_feature.\n")

    plain = skill_prompt("tdd-start", None, tmp_path)
    given = skill_prompt("tdd-start", {"arguments": "f tests/test_f.py"}, tmp_path)

    assert plain.description == "Start a feature"
    assert plain.messages[0].role == "user"
    assert plain.messages[0].content.text == "Call init_feature.\n"
    assert given.messages[0].content.text == (
        "Call init_feature.\n\nArguments given: f tests/test_f.py\n"
    )


def test_an_unknown_skill_is_an_error(tmp_path):
    skill(tmp_path, "tdd-start", "Start a feature", "Call init_feature.\n")

    with pytest.raises(ValueError, match="no-such-skill"):
        skill_prompt("no-such-skill", None, tmp_path)
    with pytest.raises(ValueError):
        skill_prompt("../tdd-start", None, tmp_path)
