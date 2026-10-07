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
    def from_json(data: Any) -> "AdapterResult":
        if not isinstance(data, dict):
            raise AdapterError(
                f"Adapter output must be a JSON object, got {type(data).__name__}"
            )
        for key in ("passed", "failed"):
            if key not in data:
                raise AdapterError(f"Adapter output missing required field '{key}'")
        failures = data.get("failures", [])
        if not isinstance(failures, list):
            raise AdapterError(
                f"Adapter output 'failures' must be a list, got {failures!r}"
            )
        for entry in failures:
            has_required_fields = (
                isinstance(entry, dict)
                and isinstance(entry.get("name"), str)
                and isinstance(entry.get("message"), str)
            )
            if not has_required_fields:
                raise AdapterError(
                    "Adapter output 'failures' entries must be objects with "
                    f"string 'name'/'message' fields, got {entry!r}"
                )
        passed = _count(data, "passed")
        failed = _count(data, "failed")
        # Durations are informational, so a float from a custom adapter is
        # fine — only counts must be exact integers.
        duration = data.get("duration_ms", 0)
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise AdapterError(
                f"Adapter output field 'duration_ms' must be a number, got {duration!r}"
            )
        duration_ms = int(duration)
        if duration_ms < 0:
            raise AdapterError(
                f"Adapter output field 'duration_ms' must be "
                f"non-negative, got {duration_ms}"
            )

        return AdapterResult(
            passed=passed,
            failed=failed,
            duration_ms=duration_ms,
            failures=failures,
            raw_output=str(data.get("raw_output", "")),
        )


def _count(data: dict[str, Any], key: str) -> int:
    """A required non-negative integer count — no bools, floats or strings."""
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdapterError(
            f"Adapter output field '{key}' must be an integer, got {value!r}"
        )
    if value < 0:
        raise AdapterError(
            f"Adapter output field '{key}' must be non-negative, got {value}"
        )
    return value


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
