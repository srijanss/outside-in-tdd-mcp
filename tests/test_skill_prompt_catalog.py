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


def test_the_workflow_docs_a_skill_refers_to_are_served_with_it(tmp_path):
    skills, docs = tmp_path / "skills", tmp_path / "docs"
    skill(skills, "implement-and-review", "Implement",
          "Read `.agents/docs/loop.md` and follow it.\n")
    docs.mkdir()
    (docs / "loop.md").write_text(
        "# Loop\n\nRead `.agents/docs/loop.md` again, then `.agents/docs/check.md`.\n"
        "Ignore `.agents/docs/missing.md`.\n"
    )
    (docs / "check.md").write_text("# Check\n\nRun the checks.\n")
    (docs / "unrelated.md").write_text("# Unrelated\n")

    text = skill_prompt(
        "implement-and-review", {"arguments": "feat-a"}, skills, docs
    ).messages[0].content.text

    assert text.startswith("Read `.agents/docs/loop.md` and follow it.\n")
    # each referenced doc once, transitively, in reference order
    assert text.count("# Loop\n") == 1 and text.count("# Check\n") == 1
    assert text.index("# Loop\n") < text.index("# Check\n")
    assert "## `.agents/docs/loop.md`" in text
    assert "## `.agents/docs/check.md`" in text
    assert "Unrelated" not in text and "## `.agents/docs/missing.md`" not in text
    assert text.endswith("\n\nArguments given: feat-a\n")


def test_a_skill_without_doc_references_is_served_unchanged(tmp_path):
    skill(tmp_path / "skills", "why-failed", "Explain", "Explain the failure.\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "loop.md").write_text("# Loop\n")

    text = skill_prompt(
        "why-failed", None, tmp_path / "skills", tmp_path / "docs"
    ).messages[0].content.text

    assert text == "Explain the failure.\n"
