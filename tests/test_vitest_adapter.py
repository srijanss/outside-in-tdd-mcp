import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = PROJECT_ROOT / "adapters" / "vitest-adapter" / "run.sh"
FIXTURE_PROJECT = PROJECT_ROOT / "tests" / "fixtures" / "vitest_project"


def run_adapter(test_target):
    proc = subprocess.run(
        [str(ADAPTER), test_target, str(FIXTURE_PROJECT)],
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


def test_adapter_reports_all_passing_normally():
    result = run_adapter("passing.test.js")
    assert result["failed"] == 0
    assert result["passed"] > 0
    assert result["failures"] == []


def test_adapter_reports_genuine_assertion_failure():
    result = run_adapter("failing.test.js")
    assert result["failed"] == 1
    assert result["passed"] == 0
    assert len(result["failures"]) == 1
    assert result["failures"][0]["name"] == "expects the wrong value"
    assert "expected 2 to be 3" in result["failures"][0]["message"]


def test_adapter_reports_failure_when_collection_is_interrupted():
    # A file that fails to import (missing module, syntax error, etc.)
    # aborts before any test runs, so there are no assertionResults — the
    # adapter must not silently report passed=0/failed=0 in that case.
    result = run_adapter("broken.test.js")
    assert result["failed"] >= 1
    assert result["passed"] == 0


def test_adapter_does_not_treat_no_tests_found_as_a_failure():
    # vitest exits non-zero when a target matches no test files at all —
    # an empty selection isn't the same as a failure, so the adapter must
    # not surface it as one.
    result = run_adapter("nonexistent.test.js")
    assert result["passed"] == 0
    assert result["failed"] == 0
    assert result["failures"] == []


def test_adapter_handles_multiple_space_separated_targets_without_double_counting():
    # A space-separated target list is parsed with shlex into multiple
    # files. numFailedTests from vitest's own summary never includes a
    # suite that failed before any test ran (e.g. a bad import), so the
    # adapter's own "+1 per suite-level failure" must not double-count it
    # against a mix of a real failing test and a collection failure.
    result = run_adapter("broken.test.js passing.test.js failing.test.js")
    assert result["passed"] == 1
    assert result["failed"] == 2
    assert len(result["failures"]) == 2


def test_adapter_reports_a_hook_failure_as_a_test_failure():
    # A beforeEach/beforeAll hook that throws surfaces as a normal failed
    # assertionResult (not a suite-level failure), so the adapter's usual
    # per-test loop must catch it without any special-casing.
    result = run_adapter("hook_error.test.js")
    assert result["passed"] == 0
    assert result["failed"] == 1
    assert len(result["failures"]) == 1
    assert "boom in beforeEach" in result["failures"][0]["message"]
