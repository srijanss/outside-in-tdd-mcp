"""The server's workflow skills, served as MCP prompts.

Each skill is core/skills/<name>/SKILL.md: YAML-style frontmatter (name,
description) followed by the instructions. prompts/list shows the
frontmatter; prompts/get returns the instructions, plus whatever free-text
arguments the caller passed, so a project needs no skill copies of its own.
"""

from pathlib import Path

from mcp import types

SKILLS_DIR = Path(__file__).resolve().parent / "skills"
ARGUMENTS = types.PromptArgument(
    name="arguments",
    description="Free-text arguments for the skill (feature names, test file, options).",
    required=False,
)


def _read_skill(path: Path) -> tuple[dict[str, str], str]:
    """(frontmatter fields, body) of a SKILL.md."""
    text = path.read_text()
    if not text.startswith("---\n"):
        return {}, text
    header, _, body = text[len("---\n"):].partition("\n---\n")
    fields = {}
    for line in header.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields, body.lstrip("\n")


def _skill_files(skills_dir: Path) -> dict[str, Path]:
    if not skills_dir.is_dir():
        return {}
    return {
        path.parent.name: path
        for path in sorted(skills_dir.glob("*/SKILL.md"))
    }


def skill_prompts(skills_dir: Path = SKILLS_DIR) -> list[types.Prompt]:
    prompts = []
    for name, path in _skill_files(skills_dir).items():
        fields, _ = _read_skill(path)
        prompts.append(
            types.Prompt(
                name=name,
                description=fields.get("description"),
                arguments=[ARGUMENTS],
            )
        )
    return prompts


def skill_prompt(
    name: str, arguments: dict[str, str] | None, skills_dir: Path = SKILLS_DIR
) -> types.GetPromptResult:
    path = _skill_files(skills_dir).get(name)
    if path is None:
        raise ValueError(f"Unknown prompt: {name}")
    fields, body = _read_skill(path)
    given = ((arguments or {}).get("arguments") or "").strip()
    if given:
        body = f"{body.rstrip()}\n\nArguments given: {given}\n"
    return types.GetPromptResult(
        description=fields.get("description"),
        messages=[
            types.PromptMessage(
                role="user", content=types.TextContent(type="text", text=body)
            )
        ],
    )
