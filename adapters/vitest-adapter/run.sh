#!/usr/bin/env python3
"""adapters/vitest-adapter/run.sh

Contract: ./run.sh <test_target> <project_root>
A target of "related <file>..." runs `vitest related --run <file>...`.
Prints exactly one JSON object to stdout: {passed, failed, duration_ms, failures, raw_output}
"""
import json
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main() -> int:
    test_target = sys.argv[1] if len(sys.argv) > 1 else ""
    project_root = sys.argv[2] if len(sys.argv) > 2 else "."

    target_args = shlex.split(test_target)
    if target_args[:1] == ["related"]:
        # "related <file>..." (from scope.sh): only the tests whose import
        # graph reaches a named file; --run keeps vitest out of watch mode.
        command = ["related", "--run", *target_args[1:]]
    else:
        command = ["run", *target_args]

    with tempfile.TemporaryDirectory(prefix="tdd-vitest-adapter-") as tmpdir:
        report_file = Path(tmpdir) / "report.json"

        start = time.monotonic()
        proc = subprocess.run(
            [
                "npx",
                "vitest",
                *command,
                "--reporter=json",
                f"--outputFile={report_file}",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        raw_output = proc.stdout + proc.stderr

        try:
            report = json.loads(report_file.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            result = {
                "passed": 0,
                "failed": 1,
                "duration_ms": duration_ms,
                "failures": [
                    {"name": "collection", "message": raw_output[-500:]}
                ],
                "raw_output": raw_output[-3000:],
            }
            print(json.dumps(result))
            return 0

    failures = []
    failed = report.get("numFailedTests", 0)
    for test_result in report.get("testResults", []):
        assertions = test_result.get("assertionResults", [])
        for assertion in assertions:
            if assertion.get("status") == "failed":
                failures.append(
                    {
                        "name": assertion.get("fullName", assertion.get("title", "")),
                        "message": "\n".join(assertion.get("failureMessages", []))[:500],
                    }
                )
        if not assertions and test_result.get("status") == "failed":
            # Collection was interrupted (e.g. a bad import) before any
            # test ran, so there are no assertionResults to report — the
            # suite-level failure is the only signal we have.
            failed += 1
            failures.append(
                {
                    "name": "collection",
                    "message": str(test_result.get("message", ""))[:500],
                }
            )

    result = {
        "passed": report.get("numPassedTests", 0),
        "failed": failed,
        "duration_ms": duration_ms,
        "failures": failures,
        "raw_output": raw_output[-3000:],
    }

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
