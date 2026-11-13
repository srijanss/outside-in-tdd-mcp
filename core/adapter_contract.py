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
import signal
import subprocess
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TIMEOUT_S = 120
# How long to wait for a SIGKILLed adapter to be reaped.
_CLEANUP_WAIT_S = 5


class AdapterError(Exception):
    """Raised when an adapter can't be run or returns malformed output."""


class AdapterTimeoutError(AdapterError):
    """The adapter ran past its timeout; ``timeout_s`` is the limit it hit."""

    def __init__(self, message: str, timeout_s: int) -> None:
        super().__init__(message)
        self.timeout_s = timeout_s


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
        # Own session/process group, so a timeout can kill the whole tree —
        # an adapter that forks (no exec) would otherwise leave its children
        # running and holding the stdout pipe open.
        proc = subprocess.Popen(
            [adapter_path, test_target, project_root],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise AdapterError(f"Adapter not found at '{adapter_path}'") from exc
    try:
        raw_stdout, raw_stderr = proc.communicate(timeout=max(timeout_s, 0))
    except subprocess.TimeoutExpired as exc:
        _kill_process_group(proc)
        raise AdapterTimeoutError(
            f"Adapter timed out after {timeout_s}s: {adapter_path}", timeout_s
        ) from exc
    except BaseException:
        # Interrupted (e.g. KeyboardInterrupt): don't orphan the adapter.
        _kill_process_group(proc)
        raise

    stdout = raw_stdout.strip()
    if not stdout:
        raise AdapterError(
            f"Adapter produced no stdout output (exit code {proc.returncode}). "
            f"stderr: {raw_stderr[-1000:]}"
        )

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AdapterError(
            f"Adapter did not print valid JSON. stdout: {stdout[-1000:]}"
        ) from exc

    return AdapterResult.from_json(data)


def _kill_process_group(proc: subprocess.Popen) -> None:
    """SIGKILL the adapter's whole process group, then reap the adapter.

    Bounded on purpose: a descendant that left the group (setsid) may still
    hold the pipes, so close them instead of waiting for EOF.
    """
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    for pipe in (proc.stdout, proc.stderr):
        if pipe is not None:
            pipe.close()
    try:
        proc.wait(timeout=_CLEANUP_WAIT_S)
    except subprocess.TimeoutExpired:
        # Not reaped in time (e.g. stuck in uninterruptible I/O). Don't let
        # cleanup replace the caller's error; subprocess reaps the zombie
        # later via its own _active list once proc is collected.
        pass


def scope_for_changed_files(
    adapter_path: str,
    project_root: str,
    changed_files: list[str],
    timeout_s: int = 30,
) -> str | None:
    """The adapter's own regression scope for ``changed_files``, or None.

    Optional extension of the adapter contract: an executable ``scope.sh``
    next to the adapter, called as ``scope.sh <project_root> <file>...``,
    prints ``{"scope": "<test target expression>"}`` — or ``{"scope":
    null}`` when it can't map the files. A missing, failing, hanging or
    malformed script means no mapping, so the caller falls back to the
    whole suite.
    """
    if not changed_files:
        return None
    script = os.path.join(os.path.dirname(adapter_path), "scope.sh")
    if not os.access(script, os.X_OK):
        return None
    try:
        proc = subprocess.Popen(
            [script, project_root, *changed_files],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return None
    try:
        stdout, _ = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        return None
    except BaseException:
        _kill_process_group(proc)
        raise
    if proc.returncode != 0:
        return None
    try:
        # Bytes in: invalid UTF-8 surfaces here as a ValueError too.
        data = json.loads(stdout)
    except ValueError:
        return None
    scope = data.get("scope") if isinstance(data, dict) else None
    if not isinstance(scope, str) or not scope.strip():
        return None
    return scope.strip()
