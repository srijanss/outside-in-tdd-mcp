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
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    test_target = sys.argv[1] if len(sys.argv) > 1 else ""
    project_root = sys.argv[2] if len(sys.argv) > 2 else "."

    target_args = shlex.split(test_target)

    with tempfile.TemporaryDirectory(prefix="tdd-adapter-") as tmpdir:
        report_file = Path(tmpdir) / "report.json"

        proc = subprocess.run(
            [
                "pytest",
                *target_args,
                "-v",
                "--tb=short",
                "--json-report",
                f"--json-report-file={report_file}",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        raw_output = proc.stdout + proc.stderr

        try:
            report = json.loads(report_file.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            # pytest failed before it could produce a report at all
            # (e.g. pytest itself not found, bad cwd).
            result = {
                "passed": 0,
                "failed": 1,
                "duration_ms": 0,
                "failures": [{"name": "collection", "message": raw_output[-500:]}],
                "raw_output": raw_output[-3000:],
            }
            print(json.dumps(result))
            return 0

    failures = []
    for test in report.get("tests", []):
        if test["outcome"] == "failed":
            failures.append(
                {
                    "name": test["nodeid"],
                    "message": str(test.get("call", {}).get("longrepr", ""))[:500],
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
            {"name": "collection", "message": raw_output[-500:]}
        )
    elif proc.returncode in (2, 3, 4):
        # Collection interrupted entirely (ImportError, syntax error, bad
        # path, bad -m expression, ...) before any test ran — distinct from
        # the per-test errors above: summary has no "error" key at all
        # here, so exit code (2=interrupted, 3=internal, 4=usage error) is
        # the only remaining signal. Exit code 5 ("no tests collected") is
        # excluded on purpose — an empty selection isn't a failure.
        failed += 1
        failures.append({"name": "collection", "message": raw_output[-500:]})

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
