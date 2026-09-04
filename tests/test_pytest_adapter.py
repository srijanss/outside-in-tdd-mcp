import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh"
BROKEN_FIXTURE = "tests/fixtures/broken_import_module.py"
REAL_FAILURE_FIXTURE = "tests/fixtures/real_assertion_failure.py"
NO_TESTS_FIXTURE = "tests/fixtures/no_tests_collected.py"
SETUP_ERROR_FIXTURE = "tests/fixtures/setup_error.py"


def run_adapter(test_target):
    proc = subprocess.run(
        [str(ADAPTER), test_target, str(PROJECT_ROOT)],
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


def test_adapter_reports_failure_when_collection_is_interrupted():
    # A file that fails to import (syntax error, bad import, etc.) aborts
    # pytest's collection entirely before any test runs. The adapter must
    # not silently report passed=0/failed=0 in that case.
    result = run_adapter(BROKEN_FIXTURE)
    assert result["failed"] >= 1
    assert result["passed"] == 0


def test_adapter_reports_all_passing_normally():
    result = run_adapter("tests/test_state_machine.py")
    assert result["failed"] == 0
    assert result["passed"] > 0
    assert result["failures"] == []


def test_adapter_reports_genuine_assertion_failure_without_extra_collection_entry():
    result = run_adapter(REAL_FAILURE_FIXTURE)
    assert result["passed"] == 0
    assert result["failed"] == 1
    # A genuine assertion failure must not also get the synthetic
    # "collection" entry — that's reserved for collection-time errors.
    assert all(f["name"] != "collection" for f in result["failures"])


def test_adapter_does_not_report_failure_when_no_tests_are_collected():
    # A valid file with zero test functions in it is not a collection
    # error — pytest exits 5 ("no tests ran") for this, distinct from an
    # ImportError/syntax error (exit 2). Nothing failed; nothing should be
    # reported as failed.
    result = run_adapter(NO_TESTS_FIXTURE)
    assert result["passed"] == 0
    assert result["failed"] == 0


def test_adapter_reports_failure_when_target_mixes_broken_and_passing_files():
    # A multi-path target (shlex-split, per the adapter's documented
    # contract) where one file fails to import and another is a normal
    # passing suite. pytest aborts the whole session on the collection
    # error, so nothing from the passing file should be reported as
    # passed either — the failure must still be surfaced, not swallowed.
    mixed_target = f"{BROKEN_FIXTURE} tests/test_state_machine.py"
    result = run_adapter(mixed_target)
    assert result["failed"] >= 1
    assert result["passed"] == 0


def test_adapter_reports_failure_when_a_fixture_raises_during_setup():
    # A fixture that raises during setup produces a per-test "error"
    # outcome (distinct from a full collection interrupt) — pytest exits 1
    # and pytest-json-report's summary carries an "error" count for it.
    # The adapter's `if errors:` branch is what's meant to catch this.
    result = run_adapter(SETUP_ERROR_FIXTURE)
    assert result["passed"] == 0
    assert result["failed"] >= 1
