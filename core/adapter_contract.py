"""The interface every test-runner adapter must satisfy.

An adapter is any executable at a known path that:
  - takes exactly two positional CLI args: <test_target> <project_root>
  - prints exactly one JSON object to stdout matching AdapterResult's shape
  - may exit non-zero (failing tests isn't a script error)

This module has zero language/framework-specific knowledge. It only knows
how to invoke an adapter executable and validate/parse its output.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TIMEOUT_S = 120


class AdapterError(Exception):
    """Raised when an adapter can't be run or returns malformed output."""


@dataclass
class AdapterResult:
    passed: int
    failed: int
    duration_ms: int = 0
    failures: list = field(default_factory=list)
    raw_output: str = ""

    @staticmethod
    def from_json(data: dict[str, Any]) -> "AdapterResult":
        for key in ("passed", "failed"):
            if key not in data:
                raise AdapterError(f"Adapter output missing required field '{key}'")
        failures = list(data.get("failures", []))
        for entry in failures:
            has_required_fields = (
                isinstance(entry, dict) and "name" in entry and "message" in entry
            )
            if not has_required_fields:
                raise AdapterError(
                    "Adapter output 'failures' entries must be objects with "
                    f"'name'/'message' fields, got {entry!r}"
                )
        passed = int(data["passed"])
        failed = int(data["failed"])
        duration_ms = int(data.get("duration_ms", 0))
        for field_name, value in (
            ("passed", passed),
            ("failed", failed),
            ("duration_ms", duration_ms),
        ):
            if value < 0:
                raise AdapterError(
                    f"Adapter output field '{field_name}' must be "
                    f"non-negative, got {value}"
                )

        return AdapterResult(
            passed=passed,
            failed=failed,
            duration_ms=duration_ms,
            failures=failures,
            raw_output=str(data.get("raw_output", "")),
        )


def run_adapter(
    adapter_path: str,
    test_target: str,
    project_root: str,
    timeout_s: int | None = None,
) -> AdapterResult:
    """Invoke the adapter executable and parse its JSON stdout contract.

    timeout_s defaults to the TDD_ADAPTER_TIMEOUT_S environment variable
    (set per project via .mcp.json's env block) when not given explicitly,
    falling back to DEFAULT_TIMEOUT_S — slow suites can override it without
    a code change.
    """
    if timeout_s is None:
        raw_timeout = os.environ.get("TDD_ADAPTER_TIMEOUT_S")
        if raw_timeout is None:
            timeout_s = DEFAULT_TIMEOUT_S
        else:
            try:
                timeout_s = int(raw_timeout)
            except ValueError as exc:
                raise AdapterError(
                    f"TDD_ADAPTER_TIMEOUT_S must be an integer, got {raw_timeout!r}"
                ) from exc
    try:
        proc = subprocess.run(
            [adapter_path, test_target, project_root],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except FileNotFoundError as exc:
        raise AdapterError(f"Adapter not found at '{adapter_path}'") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdapterError(
            f"Adapter timed out after {timeout_s}s: {adapter_path}"
        ) from exc

    stdout = proc.stdout.strip()
    if not stdout:
        raise AdapterError(
            f"Adapter produced no stdout output (exit code {proc.returncode}). "
            f"stderr: {proc.stderr[-1000:]}"
        )

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AdapterError(
            f"Adapter did not print valid JSON. stdout: {stdout[-1000:]}"
        ) from exc

    return AdapterResult.from_json(data)
