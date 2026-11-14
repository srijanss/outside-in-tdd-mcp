"""The workflow skills and docs the server serves stay identical to this
repo's own .agents/skills and .agents/docs copies. That they ship in an
installed wheel is checked by test_skill_prompts_installed.py."""

from pathlib import Path

from core.skill_prompts import DOCS_DIR, SKILLS_DIR

REPO = Path(__file__).resolve().parents[1]
WORKFLOW_SKILLS = {
    "catch-up", "checkpoint", "diff-review", "flaky-check",
    "implement-and-review", "refresh", "review-and-fix", "run-only",
    "tdd-backfill-features", "tdd-complete", "tdd-plan-features",
    "tdd-refactor", "tdd-research", "tdd-resume", "tdd-resume-skeleton",
    "tdd-review", "tdd-start", "tdd-start-skeleton", "tdd-start-verify",
    "tdd-status", "why-failed",
}


def test_the_packaged_workflow_skills_match_the_repo_copies():
    packaged = {path.parent.name for path in SKILLS_DIR.glob("*/SKILL.md")}

    assert packaged == WORKFLOW_SKILLS
    for name in WORKFLOW_SKILLS:
        assert (SKILLS_DIR / name / "SKILL.md").read_text() == (
            REPO / ".agents" / "skills" / name / "SKILL.md"
        ).read_text(), name


def test_the_packaged_workflow_docs_match_the_repo_copies():
    repo_docs = REPO / ".agents" / "docs"

    assert {p.name for p in DOCS_DIR.glob("*.md")} == {
        p.name for p in repo_docs.glob("*.md")
    }
    for path in repo_docs.glob("*.md"):
        assert (DOCS_DIR / path.name).read_text() == path.read_text(), path.name


def test_no_workflow_doc_embeds_a_skill():
    # A doc is appended to every skill that refers to it, so a skill pasted
    # into one (frontmatter and all) would be served to the wrong skills.
    for path in DOCS_DIR.glob("*.md"):
        text = path.read_text()
        assert not any(
            line.startswith(("name: ", "description: ")) for line in text.splitlines()
        ), path.name
        assert "You have been given" not in text, path.name
