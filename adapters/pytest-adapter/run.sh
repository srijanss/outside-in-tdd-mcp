#!/bin/bash
# adapters/pytest-adapter/run.sh
#
# Contract: ./run.sh <test_target> <project_root>
# Prints exactly one JSON object to stdout: {passed, failed, duration_ms, failures, raw_output}
set -u

TEST_TARGET=$1
PROJECT_ROOT=$2

REPORT_FILE=$(mktemp -t tdd-report.XXXXXX.json)
RAW_FILE=$(mktemp -t tdd-raw.XXXXXX.txt)
trap 'rm -f "$REPORT_FILE" "$RAW_FILE"' EXIT

cd "$PROJECT_ROOT" || exit 1

pytest "$TEST_TARGET" -v --tb=short --json-report --json-report-file="$REPORT_FILE" > "$RAW_FILE" 2>&1 || true

REPORT_FILE="$REPORT_FILE" RAW_FILE="$RAW_FILE" python3 <<'EOF'
import json
import os

report_file = os.environ["REPORT_FILE"]
raw_file = os.environ["RAW_FILE"]

with open(raw_file) as f:
    raw_output = f.read()

try:
    with open(report_file) as f:
        report = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    # pytest failed before it could produce a report (e.g. collection error)
    result = {
        "passed": 0,
        "failed": 1,
        "duration_ms": 0,
        "failures": [{"name": "collection", "message": raw_output[-500:]}],
        "raw_output": raw_output[-3000:],
    }
    print(json.dumps(result))
    raise SystemExit(0)

failures = []
for test in report.get("tests", []):
    if test["outcome"] == "failed":
        failures.append({
            "name": test["nodeid"],
            "message": str(test.get("call", {}).get("longrepr", ""))[:500],
        })

result = {
    "passed": report["summary"].get("passed", 0),
    "failed": report["summary"].get("failed", 0),
    "duration_ms": int(report.get("duration", 0) * 1000),
    "failures": failures,
    "raw_output": raw_output[-3000:],
}

print(json.dumps(result))
EOF
