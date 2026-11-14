"""The workflow skills the server serves ship inside the core package (so
pip/Docker installs have them), and stay identical to this repo's own
.agents/skills copies."""

from pathlib import Path

from core.skill_prompts import SKILLS_DIR

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


def test_the_skills_ship_as_package_data():
    assert '"skills/*/SKILL.md"' in (REPO / "pyproject.toml").read_text()
