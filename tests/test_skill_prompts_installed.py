"""The skills and workflow docs are served by an *installed* server: build the
wheel, install it into a fresh venv outside the checkout, and talk to that
venv's outside-in-tdd-mcp over stdio from a bare project. Nothing may come
from the source tree, so a missing package-data entry fails here.

The wheel is installed with --no-deps (no network needed); its dependencies
come from this test run's own site-packages, added as a plain path, which
doesn't run that directory's .pth files, so the dev venv's editable install
of `core` stays out of the picture."""

import json
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tests.test_skill_prompts_packaging import WORKFLOW_SKILLS

REPO = Path(__file__).resolve().parents[1]
UV = shutil.which("uv")
BUILD_LEFTOVERS = (
    ".git", ".venv", "build", "dist", "*.egg-info", "__pycache__",
    ".pytest_cache", ".project-mcp", "node_modules", "target", ".claude",
)


def site_packages(python: Path) -> Path:
    out = subprocess.run(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        capture_output=True, text=True, check=True,
    )
    return Path(out.stdout.strip())


@pytest.fixture(scope="module")
def installed_venv(tmp_path_factory):
    if UV is None:
        pytest.skip("uv is needed to build and install the wheel")
    work = tmp_path_factory.mktemp("installed")
    source, dist, venv = work / "source", work / "dist", work / "venv"
    # Build from a clean copy: an in-tree build reuses a stale build/ or
    # *.egg-info, which can put files in the wheel that package-data doesn't.
    shutil.copytree(REPO, source, ignore=shutil.ignore_patterns(*BUILD_LEFTOVERS))
    run = lambda *args: subprocess.run(args, check=True, capture_output=True, timeout=300)
    run(UV, "build", "--wheel", "-q", "-o", str(dist), str(source))
    run(UV, "venv", "-q", "--python", sys.executable, str(venv))
    python = venv / "bin" / "python"
    run(UV, "pip", "install", "-q", "--no-deps", "--offline",
        "--python", str(python), *map(str, dist.glob("*.whl")))
    (site_packages(python) / "_test_deps.pth").write_text(
        sysconfig.get_paths()["purelib"] + "\n"
    )
    return venv


async def served(server: Path, root: Path):
    (root / ".tdd-config.json").write_text(
        json.dumps({"adapter": "fake", "adapterPath": "./fake_adapter.py"})
    )
    params = StdioServerParameters(
        command=str(server),
        cwd=str(root),
        env={"PATH": os.environ["PATH"], "HOME": str(root), "TDD_PROJECT_ROOT": str(root)},
    )
    with anyio.fail_after(60):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = (await session.list_prompts()).prompts
                loop = await session.get_prompt("implement-and-review", {})
                return listed, loop


def test_the_installed_wheel_serves_the_skills_and_their_docs(installed_venv, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    origin = subprocess.run(
        [str(installed_venv / "bin" / "python"), "-I", "-c",
         "import core.skill_prompts as m; print(m.__file__)"],
        cwd=project, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert Path(origin).is_relative_to(installed_venv), origin

    listed, loop = anyio.run(served, installed_venv / "bin" / "outside-in-tdd-mcp", project)

    assert {prompt.name for prompt in listed} == WORKFLOW_SKILLS
    text = loop.messages[0].content.text
    assert "Read `.agents/docs/review-loop.md`" in text
    assert "Shared by `implement-and-review` and `review-and-fix`." in text
