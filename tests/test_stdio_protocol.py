"""End-to-end smoke test over the real MCP stdio transport.

Everything else tests TDDServer in-process; this starts the installed
console script as a subprocess in a throwaway project and talks to it with
the MCP client, so tool registration, schemas and JSON framing are covered
too. The project is a temp dir with a scripted fake adapter, and the
server's environment is built from scratch, so it never sees this repo's
own .tdd-state.json.
"""

import json
import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(sys.executable).parent / "outside-in-tdd-mcp"

FAKE_ADAPTER = f"""#!{sys.executable}
# Prints whatever result the test scripted into next_result.json.
import json, pathlib, sys
result = json.loads((pathlib.Path(sys.argv[2]) / "next_result.json").read_text())
print(json.dumps({{**result, "duration_ms": 1, "failures": [], "raw_output": ""}}))
"""


def make_project(root: Path) -> None:
    adapter = root / "fake_adapter.py"
    adapter.write_text(FAKE_ADAPTER)
    adapter.chmod(0o755)
    (root / ".tdd-config.json").write_text(
        json.dumps({"adapter": "fake", "adapterPath": "./fake_adapter.py"})
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_feature.py").write_text("def test_feature(): ...\n")
    (root / "tests" / "test_unit.py").write_text("def test_unit(): ...\n")
    (root / "impl.py").write_text("VALUE = 1\n")


async def drive_a_nested_feature(root: Path) -> None:
    params = StdioServerParameters(
        command=str(SERVER),
        cwd=str(root),
        # Built from scratch so no TDD_* path override can leak in.
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(root),
            "TDD_PROJECT_ROOT": str(root),
        },
    )

    def script_result(passed, failed):
        (root / "next_result.json").write_text(
            json.dumps({"passed": passed, "failed": failed})
        )

    with anyio.fail_after(60):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def call(tool, **arguments):
                    result = await session.call_tool(tool, arguments)
                    return json.loads(result.content[0].text)

                tools = {tool.name for tool in (await session.list_tools()).tools}
                assert {
                    "init_feature", "write_test", "run_tests", "verify",
                    "write_code", "refactor_code", "drill_down",
                    "return_to_parent", "complete_feature", "get_status",
                } <= tools

                status = await call(
                    "init_feature", featureName="smoke",
                    testFile="tests/test_feature.py", targetFiles=[],
                )
                assert status["phase"] == "red"

                # An out-of-phase call comes back as an error payload and
                # changes nothing.
                assert "error" in await call("write_code", filePath="impl.py")
                assert (await call("get_status"))["phase"] == "red"

                await call("write_test", testName="test_feature")
                script_result(0, 1)
                assert (await call("run_tests", advance=True))["phase"] == "implement"

                await call("drill_down", testFile="tests/test_unit.py",
                           targetFiles=["impl.py"])
                await call("write_test", testName="test_unit")
                assert (await call("run_tests", advance=True))["phase"] == "implement"
                await call("write_code", filePath="impl.py")
                script_result(1, 0)
                assert (await call("run_tests", advance=True))["phase"] == "refactor"
                await call("refactor_code", description="none needed")
                status = await call("run_tests")
                assert (status["phase"], status["cycleCount"]) == ("red", 1)

                status = await call("return_to_parent")
                assert (status["depth"], status["phase"]) == (1, "implement")
                assert (await call("run_tests", advance=True))["phase"] == "refactor"
                await call("refactor_code", description="none needed")
                assert (await call("run_tests"))["phase"] == "red"

                done = await call("complete_feature")
                assert "error" not in done, done
                assert done["featureName"] is None


def test_a_nested_feature_runs_end_to_end_over_stdio(tmp_path):
    make_project(tmp_path)

    anyio.run(drive_a_nested_feature, tmp_path)

    # State went to the throwaway project, not this repo.
    assert (tmp_path / ".tdd-state.json").exists()
