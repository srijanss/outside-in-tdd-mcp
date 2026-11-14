"""The server serves its workflow skills as MCP prompts, so a project with
no skill copies of its own (.claude/.codex/.pi/.agents) still gets them."""

import json
import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(sys.executable).parent / "outside-in-tdd-mcp"


async def prompts_from_a_bare_project(root: Path):
    (root / ".tdd-config.json").write_text(
        json.dumps({"adapter": "fake", "adapterPath": "./fake_adapter.py"})
    )
    params = StdioServerParameters(
        command=str(SERVER),
        cwd=str(root),
        env={"PATH": os.environ["PATH"], "HOME": str(root), "TDD_PROJECT_ROOT": str(root)},
    )
    with anyio.fail_after(60):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = (await session.list_prompts()).prompts
                got = await session.get_prompt(
                    "tdd-start", {"arguments": "my-feature tests/test_my_feature.py"}
                )
                loop = await session.get_prompt("implement-and-review", {})
                return listed, got, loop


def test_workflow_skills_are_listed_and_served_as_prompts(tmp_path):
    listed, got, _ = anyio.run(prompts_from_a_bare_project, tmp_path)

    by_name = {prompt.name: prompt for prompt in listed}
    assert {"implement-and-review", "tdd-start", "tdd-start-verify"} <= set(by_name)
    assert "without a human checkpoint" in by_name["tdd-start"].description
    text = got.messages[0].content.text
    assert "init_feature" in text
    assert not text.startswith("---")  # the skill body, not its frontmatter
    assert "my-feature tests/test_my_feature.py" in text


def test_a_served_skill_carries_the_workflow_docs_it_tells_the_agent_to_read(tmp_path):
    # implement-and-review says "Read `.agents/docs/review-loop.md`", which a
    # bare project doesn't have, so the prompt has to carry that doc itself.
    assert not (tmp_path / ".agents").exists()

    *_, loop = anyio.run(prompts_from_a_bare_project, tmp_path)

    text = loop.messages[0].content.text
    assert "Read `.agents/docs/review-loop.md`" in text
    assert "Shared by `implement-and-review` and `review-and-fix`." in text
