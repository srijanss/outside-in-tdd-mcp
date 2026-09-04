"""MCP protocol handler (stdio transport). Glue between the MCP tool calls,
the phase state machine, and the configured test-runner adapter.

No language- or framework-specific logic belongs here — see adapter_contract.py
and adapters/*/run.sh for that.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import mcp.server.stdio
from mcp import types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from core.adapter_contract import AdapterError, run_adapter
from core.state_machine import NoActiveFeatureError, PhaseError, TDDStateMachine

PROJECT_ROOT = os.environ.get("TDD_PROJECT_ROOT", "/app")
CONFIG_PATH = os.environ.get(
    "TDD_CONFIG_PATH", str(Path(PROJECT_ROOT) / ".tdd-config.json")
)

TOOLS = [
    types.Tool(
        name="init_feature",
        description="Start a new TDD feature. Sets phase to RED.",
        inputSchema={
            "type": "object",
            "properties": {
                "featureName": {"type": "string"},
                "testFile": {
                    "type": "string",
                    "description": "Path relative to project root",
                },
            },
            "required": ["featureName", "testFile"],
        },
    ),
    types.Tool(
        name="write_test",
        description="Write a failing test. Only available in RED phase.",
        inputSchema={
            "type": "object",
            "properties": {
                "testName": {"type": "string"},
                "code": {"type": "string"},
            },
            "required": ["testName", "code"],
        },
    ),
    types.Tool(
        name="write_code",
        description="Write implementation code. Only available in IMPLEMENT phase.",
        inputSchema={
            "type": "object",
            "properties": {
                "filePath": {"type": "string"},
                "code": {"type": "string"},
            },
            "required": ["filePath", "code"],
        },
    ),
    types.Tool(
        name="run_tests",
        description=(
            "Run the test suite via the configured adapter. "
            "Auto-advances phase based on results."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="refactor_code",
        description="Refactor code. Only available in REFACTOR phase.",
        inputSchema={
            "type": "object",
            "properties": {"description": {"type": "string"}},
            "required": ["description"],
        },
    ),
    types.Tool(
        name="get_status",
        description="Get current feature, phase, test results, and available tools.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="reset_feature",
        description="Reset current feature. Allows starting a new one.",
        inputSchema={"type": "object", "properties": {}},
    ),
]


def load_config(config_path: str) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f".tdd-config.json not found at '{config_path}'. "
            "Create one with 'adapter', 'adapterPath', 'defaultTestDir'."
        )
    with path.open() as f:
        return json.load(f)


class TDDServer:
    def __init__(self, project_root: str, config_path: str) -> None:
        self.project_root = project_root
        self.config_path = config_path
        self.sm = TDDStateMachine()

    def _text(self, payload: dict[str, Any]) -> list[types.TextContent]:
        return [types.TextContent(type="text", text=json.dumps(payload, indent=2))]

    def _error(self, message: str) -> list[types.TextContent]:
        return self._text({"error": message})

    def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> list[types.TextContent]:
        try:
            if name == "init_feature":
                self.sm.init_feature(arguments["featureName"], arguments["testFile"])
                return self._text(self.sm.status())

            if name == "write_test":
                self.sm.write_test(arguments["testName"], arguments["code"])
                return self._text(
                    {
                        "ok": True,
                        "message": (
                            f"Test '{arguments['testName']}' recorded. "
                            "Write it to the test file, then call run_tests()."
                        ),
                        **self.sm.status(),
                    }
                )

            if name == "write_code":
                self.sm.write_code(arguments["filePath"], arguments["code"])
                return self._text(
                    {
                        "ok": True,
                        "message": (
                            f"Code change for '{arguments['filePath']}' recorded. "
                            "Write it to disk, then call run_tests()."
                        ),
                        **self.sm.status(),
                    }
                )

            if name == "refactor_code":
                self.sm.refactor_code(arguments["description"])
                return self._text(
                    {
                        "ok": True,
                        "message": (
                            f"Refactor recorded: {arguments['description']}. "
                            "Call run_tests() to confirm nothing broke."
                        ),
                        **self.sm.status(),
                    }
                )

            if name == "run_tests":
                return self._text(self._run_tests())

            if name == "get_status":
                return self._text(self.sm.status())

            if name == "reset_feature":
                self.sm.reset_feature()
                return self._text({"ok": True, **self.sm.status()})

            return self._error(f"Unknown tool: {name}")

        except (PhaseError, NoActiveFeatureError) as exc:
            return self._error(str(exc))
        except KeyError as exc:
            return self._error(f"Missing required argument: {exc}")

    def _run_tests(self) -> dict[str, Any]:
        if self.sm.phase is None:
            return {"error": "No active feature. Call init_feature() first."}

        try:
            config = load_config(self.config_path)
        except FileNotFoundError as exc:
            return {"error": str(exc)}

        adapter_path = config["adapterPath"]
        test_target = self.sm.test_file or config.get("defaultTestDir", ".")

        try:
            result = run_adapter(adapter_path, test_target, self.project_root)
        except AdapterError as exc:
            return {"error": f"Adapter failed: {exc}"}

        self.sm.record_test_result(
            passed=result.passed,
            failed=result.failed,
            duration_ms=result.duration_ms,
            failures=result.failures,
            raw_output=result.raw_output,
        )

        return {
            "testResult": {
                "passed": result.passed,
                "failed": result.failed,
                "durationMs": result.duration_ms,
                "failures": result.failures,
            },
            **self.sm.status(),
        }


def build_server() -> Server:
    tdd = TDDServer(PROJECT_ROOT, CONFIG_PATH)
    server: Server = Server("outside-in-tdd")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent]:
        return tdd.call_tool(name, arguments or {})

    return server


async def main() -> None:
    server = build_server()
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="outside-in-tdd",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def run() -> None:
    """Sync entry point for the `outside-in-tdd-mcp` console script."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
