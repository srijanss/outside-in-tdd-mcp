#!/usr/bin/env python3
"""adapters/pytest-adapter/run.sh

Contract: ./run.sh <test_target> <project_root>
Prints exactly one JSON object to stdout: {passed, failed, duration_ms, failures, raw_output}

<test_target> is parsed with shlex (real shell-word semantics — quoted
substrings stay together) so it can be a single path, several
space-separated paths/dirs, or a full pytest argument expression like
`-m "not ft" cart/ order/ promotions/tests/test_models.py`.
"""
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


def _trim_for_message(raw_output: str) -> str:
    """Drop pytest-json-report's own "JSON report" boilerplate and the
    short-summary section that follows it before capping to a message
    size — both are printed after the actual traceback, so a fixed-size
    tail slice of the untrimmed output would show only that noise and
    lose the real error.
    """
    marker_index = raw_output.rfind("JSON report")
    if marker_index == -1:
        return raw_output
    line_start = raw_output.rfind("\n", 0, marker_index)
    return raw_output[: line_start if line_start != -1 else marker_index]


_CHAIN_SEPARATOR = "During handling of the above exception, another exception occurred:"
_FRAME_LINE = re.compile(r"^(\S+?):\d+: in \S+")


def _clean_longrepr(text: str) -> str:
    """Cut a failure's traceback down to what helps fix the test: only the
    final exception of a chained failure (the earlier one is printed again
    inside it), and only frames from the project — not the ones through
    stdlib/site-packages (absolute or '../' paths, e.g. unittest.mock)."""
    if _CHAIN_SEPARATOR in text:
        text = text.rsplit(_CHAIN_SEPARATOR, 1)[1].lstrip("\n")
    kept = []
    skipping = False
    for line in text.splitlines():
        frame = _FRAME_LINE.match(line)
        if frame:
            path = frame.group(1)
            skipping = (
                path.startswith("..") or os.path.isabs(path) or "site-packages" in path
            )
        elif not line.startswith(" "):
            skipping = False  # an 'E   ...' line ends the frame's code block
        if not skipping:
            kept.append(line)
    return "\n".join(kept)


def _pytest_commands(project_root: str) -> list[str]:
    """Candidate pytest executables, in preference order: the target
    project's own .venv pytest (so tests run against the project's own
    dependencies, never the MCP server's mcpctl runtime), then whatever
    `pytest` is on PATH.
    """
    project_pytest = Path(project_root) / ".venv" / "bin" / "pytest"
    if project_pytest.is_file():
        return [str(project_pytest), "pytest"]
    return ["pytest"]


def _run_pytest(project_root: str, args: list[str]) -> subprocess.CompletedProcess:
    """Run the first candidate pytest that can actually be executed. A
    .venv built on another platform (e.g. a macOS venv bind-mounted into a
    Linux container) has a pytest whose shebang interpreter doesn't exist
    here, which makes exec fail with OSError instead of running.
    """
    candidates = _pytest_commands(project_root)
    for index, command in enumerate(candidates):
        try:
            return subprocess.run(
                [command, *args],
                cwd=project_root,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            if index == len(candidates) - 1:
                # No runnable pytest at all: no JSON report gets produced,
                # which main() turns into an adapter error instead of crashing.
                return subprocess.CompletedProcess(
                    [command, *args], 127, "", f"cannot execute {command}: {exc}"
                )
    raise AssertionError("unreachable")


def main() -> int:
    test_target = sys.argv[1] if len(sys.argv) > 1 else ""
    project_root = sys.argv[2] if len(sys.argv) > 2 else "."

    target_args = shlex.split(test_target)

    with tempfile.TemporaryDirectory(prefix="tdd-adapter-") as tmpdir:
        report_file = Path(tmpdir) / "report.json"

        proc = _run_pytest(
            project_root,
            [
                *target_args,
                "-v",
                "--tb=short",
                "--json-report",
                f"--json-report-file={report_file}",
            ],
        )
        raw_output = proc.stdout + proc.stderr

        try:
            report = json.loads(report_file.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            # pytest failed before it could produce a report at all (e.g.
            # pytest itself not found, pytest-json-report missing, bad cwd):
            # no test ran, so this is an adapter error, not a failing test —
            # print nothing to stdout and exit non-zero.
            print(
                "pytest-adapter: pytest produced no JSON report.\n"
                + raw_output[-3000:],
                file=sys.stderr,
            )
            return 1

    failures = []
    for test in report.get("tests", []):
        if test["outcome"] == "failed":
            failures.append(
                {
                    "name": test["nodeid"],
                    "message": _clean_longrepr(
                        str(test.get("call", {}).get("longrepr", ""))
                    )[-500:],
                }
            )

    summary = report.get("summary", {})
    failed = summary.get("failed", 0)
    errors = summary.get("error", 0)
    if errors:
        # Per-test "error" outcomes (e.g. a fixture raising during setup or
        # teardown) — collection ran fine, but a test errored before/after
        # its body. These don't show up in "tests" as "failed", so surface
        # them here rather than silently reporting passed=0/failed=0.
        failed += errors
        failures.append(
            {"name": "collection", "message": _trim_for_message(raw_output)[-500:]}
        )
    elif proc.returncode in (2, 3, 4):
        # Collection interrupted entirely (ImportError, syntax error, bad
        # path, bad -m expression, ...) before any test ran — distinct from
        # the per-test errors above: summary has no "error" key at all
        # here, so exit code (2=interrupted, 3=internal, 4=usage error) is
        # the only remaining signal. Exit code 5 ("no tests collected") is
        # excluded on purpose — an empty selection isn't a failure.
        failed += 1
        failures.append(
            {"name": "collection", "message": _trim_for_message(raw_output)[-500:]}
        )

    result = {
        "passed": summary.get("passed", 0),
        "failed": failed,
        "duration_ms": int(report.get("duration", 0) * 1000),
        "failures": failures,
        "raw_output": raw_output[-3000:],
    }

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
