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
import subprocess
from dataclasses import dataclass, field
from typing import Any


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
        return AdapterResult(
            passed=int(data["passed"]),
            failed=int(data["failed"]),
            duration_ms=int(data.get("duration_ms", 0)),
            failures=failures,
            raw_output=str(data.get("raw_output", "")),
        )


def run_adapter(
    adapter_path: str,
    test_target: str,
    project_root: str,
    timeout_s: int = 120,
) -> AdapterResult:
    """Invoke the adapter executable and parse its JSON stdout contract."""
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
