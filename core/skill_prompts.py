"""The server's workflow skills, served as MCP prompts.

Each skill is core/skills/<name>/SKILL.md: YAML-style frontmatter (name,
description) followed by the instructions. prompts/list shows the
frontmatter; prompts/get returns the instructions, plus whatever free-text
arguments the caller passed, so a project needs no skill copies of its own.

The skills tell the agent to read shared workflow docs at
`.agents/docs/<doc>.md`. A project using only the served prompts has no such
files, so prompts/get appends each doc a skill refers to (and the docs those
refer to) from core/docs/.
"""

import re
from pathlib import Path

from mcp import types

SKILLS_DIR = Path(__file__).resolve().parent / "skills"
DOCS_DIR = Path(__file__).resolve().parent / "docs"
DOC_REFERENCE = re.compile(r"`\.agents/docs/([A-Za-z0-9_-]+\.md)`")
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


def _referenced_docs(text: str, docs_dir: Path) -> list[tuple[str, str]]:
    """(name, contents) of each existing doc `text` refers to, transitively,
    in first-reference order."""
    found: dict[str, str] = {}
    pending = DOC_REFERENCE.findall(text)
    while pending:
        doc = pending.pop(0)
        path = docs_dir / doc
        if doc in found or not path.is_file():
            continue
        found[doc] = path.read_text()
        pending.extend(DOC_REFERENCE.findall(found[doc]))
    return list(found.items())


def _with_docs(body: str, docs_dir: Path) -> str:
    docs = _referenced_docs(body, docs_dir)
    if not docs:
        return body
    sections = "".join(
        f"\n\n## `.agents/docs/{doc}`\n\n{text.rstrip()}\n" for doc, text in docs
    )
    return (
        f"{body.rstrip()}\n\n---\n\nThe `.agents/docs/` files referred to above "
        f"follow. Use these copies; the project may not have its own.{sections}"
    )


def skill_prompt(
    name: str,
    arguments: dict[str, str] | None,
    skills_dir: Path = SKILLS_DIR,
    docs_dir: Path = DOCS_DIR,
) -> types.GetPromptResult:
    path = _skill_files(skills_dir).get(name)
    if path is None:
        raise ValueError(f"Unknown prompt: {name}")
    fields, body = _read_skill(path)
    body = _with_docs(body, docs_dir)
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
