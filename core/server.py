"""MCP protocol handler (stdio transport). Glue between the MCP tool calls,
the phase state machine, and the configured test-runner adapter.

No language- or framework-specific logic belongs here — see adapter_contract.py
and adapters/*/run.sh for that.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
from datetime import datetime, timezone
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
                    "description": (
                        "Test target(s), relative to project root (passed "
                        "as-is to the adapter, e.g. a pytest path expression)."
                    ),
                },
            },
            "required": ["featureName", "testFile"],
        },
    ),
    types.Tool(
        name="write_test",
        description=(
            "Declare a failing test written to disk (via your own file "
            "tools). Only available in RED phase."
        ),
        inputSchema={
            "type": "object",
            "properties": {"testName": {"type": "string"}},
            "required": ["testName"],
        },
    ),
    types.Tool(
        name="write_test_skeleton",
        description=(
            "Declare a TODO-annotated test stub written to disk instead of "
            "a finished test. RED phase only. Use only if the "
            "skeleton-first workflow was explicitly requested — otherwise "
            "use write_test."
        ),
        inputSchema={
            "type": "object",
            "properties": {"testName": {"type": "string"}},
            "required": ["testName"],
        },
    ),
    types.Tool(
        name="write_code",
        description=(
            "Declare implementation code written to disk (via your own "
            "file tools). Only available in IMPLEMENT phase."
        ),
        inputSchema={
            "type": "object",
            "properties": {"filePath": {"type": "string"}},
            "required": ["filePath"],
        },
    ),
    types.Tool(
        name="verify",
        description=(
            "User confirms the checkpoint (failing test or passing impl) "
            "and advances the cycle. VERIFY_RED or VERIFY_GREEN phase only."
        ),
        inputSchema={"type": "object", "properties": {}},
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
        description=(
            "Declare a refactor made on disk (via your own file tools), "
            "tests still green. Only available in REFACTOR phase."
        ),
        inputSchema={
            "type": "object",
            "properties": {"description": {"type": "string"}},
            "required": ["description"],
        },
    ),
    types.Tool(
        name="get_status",
        description="Get current feature, phase, drill-down stack, and last test result.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="reset_feature",
        description=(
            "Discard the current feature from any phase and clear state. "
            "Use complete_feature instead if it's actually done."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="complete_feature",
        description=(
            "Mark the current feature complete and clear its state. Only "
            "at base level (depth 1) in RED phase, after >=1 full cycle."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="drill_down",
        description=(
            "Push a nested test target on top of the current one (e.g. a "
            "unit test needed mid-implementation). IMPLEMENT phase only; "
            "runs its own RED->...->REFACTOR cycle. Call return_to_parent "
            "when done."
        ),
        inputSchema={
            "type": "object",
            "properties": {"testFile": {"type": "string"}},
            "required": ["testFile"],
        },
    ),
    types.Tool(
        name="return_to_parent",
        description=(
            "Pop the finished drill-down level and resume the parent. "
            "RED phase only, after >=1 full cycle at this level. Use "
            "abandon_drill_down instead if the level isn't finished."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="abandon_drill_down",
        description=(
            "Unconditionally pop the current drill-down level (no phase/"
            "cycle requirement) when it turns out unneeded. Not allowed "
            "at depth 1 — use reset_feature for that."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
]


# Caps on what a run_tests() response (and the last_result it gets stored
# as, which get_status() keeps re-sending until the next run_tests()) can
# carry — defensive against an adapter that doesn't cap its own output, and
# against a large regression check surfacing dozens of failures at once.
MAX_FAILURES_RETURNED = 20
MAX_FAILURE_MESSAGE_CHARS = 500


def _cap_failures(failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    capped = [
        {**f, "message": str(f.get("message", ""))[-MAX_FAILURE_MESSAGE_CHARS:]}
        for f in failures[:MAX_FAILURES_RETURNED]
    ]
    omitted = len(failures) - len(capped)
    if omitted > 0:
        capped.append(
            {
                "name": "...",
                "message": f"{omitted} more failure(s) omitted — rerun a "
                "narrower test_target to see them.",
            }
        )
    return capped


class ConfigError(Exception):
    """Raised when .tdd-config.json is missing, malformed, or incomplete."""


def load_config(config_path: str) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f".tdd-config.json not found at '{config_path}'. "
            "Create one with 'adapter', 'adapterPath', 'defaultTestDir'."
        )
    with path.open() as f:
        try:
            config = json.load(f)
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"'{config_path}' is not valid JSON: {exc}"
            ) from exc

    if not isinstance(config, dict):
        raise ConfigError(
            f"'{config_path}' must contain a JSON object, got {type(config).__name__}."
        )

    _require_string(config, "adapterPath", config_path, required=True)
    _require_string(config, "defaultTestDir", config_path, required=False)

    return config


def _require_string(
    config: dict[str, Any], field: str, config_path: str, *, required: bool
) -> None:
    if field not in config:
        if required:
            raise ConfigError(
                f"'{config_path}' is missing required field '{field}'."
            )
        return
    if not isinstance(config[field], str) or (required and not config[field]):
        raise ConfigError(
            f"'{config_path}' field '{field}' must be a non-empty string."
            if required
            else f"'{config_path}' field '{field}' must be a string."
        )


class TDDServer:
    def __init__(self, project_root: str, config_path: str) -> None:
        self.project_root = project_root
        self.config_path = config_path
        self.sm = TDDStateMachine()
        self.session_log_path = os.environ.get(
            "TDD_SESSION_LOG_PATH", str(Path(project_root) / ".tdd-session.log")
        )

    def _log_event(self, event: str, **fields: Any) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "featureName": self.sm.feature_name,
            "depth": self.sm.depth,
            "testFile": self.sm.test_file,
            "phase": self.sm.phase,
            **fields,
        }
        try:
            line = json.dumps(entry) + "\n"
        except TypeError:
            return  # a non-serializable field must never block the TDD cycle
        try:
            with open(self.session_log_path, "a") as f:
                f.write(line)
        except OSError:
            pass  # session logging is best-effort; never block the TDD cycle

    def _text(self, payload: dict[str, Any]) -> list[types.TextContent]:
        return [
            types.TextContent(
                type="text", text=json.dumps(payload, separators=(",", ":"))
            )
        ]

    def _error(self, message: str) -> list[types.TextContent]:
        return self._text({"error": message})

    def _try_load_config(self) -> tuple[dict[str, Any] | None, str | None]:
        try:
            return load_config(self.config_path), None
        except (FileNotFoundError, ConfigError) as exc:
            return None, str(exc)

    def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> list[types.TextContent]:
        try:
            if name == "init_feature":
                config, error = self._try_load_config()
                if error:
                    return self._error(error)
                adapter_path = config["adapterPath"]
                if not Path(adapter_path).exists():
                    return self._error(
                        f"Configured adapterPath '{adapter_path}' does not "
                        "exist. Fix .tdd-config.json before starting a "
                        "feature."
                    )
                self.sm.init_feature(arguments["featureName"], arguments["testFile"])
                self._log_event("init_feature")
                return self._text(self.sm.status(include_last_result=False))

            if name == "write_test":
                self.sm.write_test(arguments["testName"])
                self._log_event("write_test", testName=arguments["testName"])
                return self._text({"ok": True})

            if name == "write_test_skeleton":
                self.sm.write_test_skeleton(arguments["testName"])
                self._log_event(
                    "write_test_skeleton", testName=arguments["testName"]
                )
                return self._text({"ok": True})

            if name == "write_code":
                self.sm.write_code(arguments["filePath"])
                self._log_event("write_code", filePath=arguments["filePath"])
                return self._text({"ok": True})

            if name == "refactor_code":
                self.sm.refactor_code(arguments["description"])
                self._log_event(
                    "refactor_code", description=arguments["description"]
                )
                return self._text({"ok": True})

            if name == "verify":
                self.sm.verify()
                self._log_event("verify")
                return self._text(
                    {"ok": True, **self.sm.status(include_last_result=False)}
                )

            if name == "run_tests":
                return self._text(self._run_tests())

            if name == "get_status":
                return self._text(self.sm.status(include_stack=True))

            if name == "reset_feature":
                prior_feature = self.sm.feature_name
                prior_test_file = self.sm.test_file
                self.sm.reset_feature()
                self._log_event(
                    "reset_feature",
                    featureName=prior_feature,
                    testFile=prior_test_file,
                )
                return self._text(
                    {"ok": True, **self.sm.status(include_last_result=False)}
                )

            if name == "complete_feature":
                summary = self.sm.complete_feature()
                self._log_event(
                    "complete_feature",
                    featureName=summary["featureName"],
                    testFile=summary["testFile"],
                    cyclesCompleted=summary["cyclesCompleted"],
                )
                return self._text(
                    {
                        "ok": True,
                        "message": (
                            f"Feature '{summary['featureName']}' completed "
                            f"after {summary['cyclesCompleted']} cycle(s)."
                        ),
                        **self.sm.status(include_last_result=False),
                    }
                )

            if name == "drill_down":
                self.sm.drill_down(arguments["testFile"])
                self._log_event("drill_down", testFile=arguments["testFile"])
                return self._text(
                    {
                        "ok": True,
                        "message": (
                            f"Drilled into '{arguments['testFile']}' "
                            f"(depth {self.sm.depth}). Write a failing test "
                            "there, then call run_tests()."
                        ),
                        **self.sm.status(include_last_result=False),
                    }
                )

            if name == "return_to_parent":
                summary = self.sm.return_to_parent()
                self._log_event(
                    "return_to_parent",
                    testFile=summary["testFile"],
                    cyclesCompleted=summary["cyclesCompleted"],
                )
                return self._text(
                    {
                        "ok": True,
                        "message": (
                            f"Returned from '{summary['testFile']}' after "
                            f"{summary['cyclesCompleted']} cycle(s). "
                            f"Back at depth {self.sm.depth}."
                        ),
                        **self.sm.status(include_last_result=False),
                    }
                )

            if name == "abandon_drill_down":
                summary = self.sm.abandon_drill_down()
                self._log_event(
                    "abandon_drill_down",
                    testFile=summary["testFile"],
                    cyclesCompleted=summary["cycleCount"],
                )
                return self._text(
                    {
                        "ok": True,
                        "message": (
                            f"Abandoned drill-down into '{summary['testFile']}' "
                            f"(was {summary['phase'].upper()}, "
                            f"{summary['cycleCount']} cycle(s) completed). "
                            f"Back at depth {self.sm.depth}."
                        ),
                        **self.sm.status(include_last_result=False),
                    }
                )

            return self._error(f"Unknown tool: {name}")

        except (PhaseError, NoActiveFeatureError) as exc:
            return self._error(str(exc))
        except KeyError as exc:
            return self._error(f"Missing required argument: {exc}")

    def _run_tests(self) -> dict[str, Any]:
        if self.sm.phase is None:
            return {"error": "No active feature. Call init_feature() first."}

        config, error = self._try_load_config()
        if error:
            return {"error": error}

        adapter_path = config["adapterPath"]
        test_target = self.sm.test_file
        default_test_dir = config.get("defaultTestDir")

        # Closing a base-level REFACTOR cycle is what unlocks
        # complete_feature() — check the whole suite (not just this cycle's
        # target), so a regression elsewhere can't slip through unnoticed.
        # Nested drill-down levels skip this; only the outer feature's
        # cycle gates completion. test_target and defaultTestDir are run
        # together in one adapter call (rather than two separate calls
        # summed) since defaultTestDir almost always already contains
        # test_target — summing two runs would double-count the overlap,
        # and running it as a single pytest invocation lets pytest's own
        # collection dedupe overlapping paths for free.
        closing_base_refactor = (
            self.sm.phase == "refactor" and self.sm.depth == 1 and default_test_dir
        )
        run_target = (
            f"{test_target} {shlex.quote(default_test_dir)}"
            if closing_base_refactor
            else test_target
        )

        try:
            result = run_adapter(adapter_path, run_target, self.project_root)
        except AdapterError as exc:
            return {"error": f"Adapter failed: {exc}"}

        own_target_broke = None
        has_extra_regressions = False
        if closing_base_refactor and result.failed > 0:
            # Something in the combined run failed — find out whether it's
            # this cycle's own test or a pre-existing regression elsewhere,
            # only now that we actually need to know (rare path).
            try:
                own_result = run_adapter(adapter_path, test_target, self.project_root)
            except AdapterError as exc:
                return {"error": f"Adapter failed: {exc}"}
            own_target_broke = own_result.failed > 0
            has_extra_regressions = result.failed > own_result.failed
            if not own_target_broke or has_extra_regressions:
                # Either none of the combined failures are the own target's
                # (own_target_broke is False), or the own target broke *and*
                # something else also failed — label every failure that
                # isn't one of the own target's as a regression, in both
                # cases, instead of only when the own target is entirely
                # clean.
                own_failure_names = {f["name"] for f in own_result.failures}
                result.failures = [
                    f
                    if own_target_broke and f["name"] in own_failure_names
                    else {"name": f"REGRESSION: {f['name']}", "message": f["message"]}
                    for f in result.failures
                ]

        capped_failures = _cap_failures(result.failures)

        self.sm.record_test_result(
            passed=result.passed,
            failed=result.failed,
            duration_ms=result.duration_ms,
            failures=capped_failures,
            raw_output=result.raw_output,
        )
        self._log_event(
            "run_tests",
            passed=result.passed,
            failed=result.failed,
            durationMs=result.duration_ms,
        )

        if own_target_broke is False:
            # record_test_result's generic REFACTOR-failure message ("Refactor
            # broke the tests.") is wrong here — this cycle's own test passed;
            # the failure came from elsewhere in the suite.
            self.sm.set_last_error(
                "Regression check found pre-existing failures elsewhere "
                "(not caused by this refactor) — see the REGRESSION: "
                "entries in failures."
            )
        elif own_target_broke and has_extra_regressions:
            # Both problems are real here — say so, rather than letting the
            # generic "Refactor broke the tests." message imply that fixing
            # the own test is all that's needed.
            self.sm.set_last_error(
                "Refactor broke the tests, and the regression check also "
                "found pre-existing failures elsewhere (not caused by this "
                "refactor) — see the REGRESSION: entries in failures."
            )

        return {
            "testResult": {
                "passed": result.passed,
                "failed": result.failed,
                "durationMs": result.duration_ms,
                "failures": capped_failures,
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
