import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh"
BROKEN_FIXTURE = "tests/fixtures/broken_import_module.py"
REAL_FAILURE_FIXTURE = "tests/fixtures/real_assertion_failure.py"
NO_TESTS_FIXTURE = "tests/fixtures/no_tests_collected.py"
SETUP_ERROR_FIXTURE = "tests/fixtures/setup_error.py"
LONG_MESSAGE_FIXTURE = "tests/fixtures/long_traceback_failure.py"


def run_adapter(test_target):
    proc = subprocess.run(
        [str(ADAPTER), test_target, str(PROJECT_ROOT)],
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


def test_adapter_keeps_the_actual_error_in_a_collection_failure_message():
    # pytest-json-report prints "JSON report" boilerplate and a short
    # summary after the real traceback, which pushes the actual exception
    # (e.g. ModuleNotFoundError) out of a fixed-size tail slice of
    # raw_output — the collection message must surface it anyway.
    result = run_adapter(BROKEN_FIXTURE)
    message = result["failures"][0]["message"]
    assert "this_module_does_not_exist_at_all_xyz" in message


def test_adapter_uses_the_last_json_report_marker_not_the_first():
    # A collection error whose own traceback text coincidentally contains
    # the literal phrase "JSON report" (plausible in this project, which
    # is itself about JSON reporting) must not have its trim point land on
    # that earlier match — only the real pytest-json-report boilerplate
    # marker (always the last such occurrence) should be stripped.
    result = run_adapter("tests/fixtures/collection_error_mentions_json_report.py")
    message = result["failures"][0]["message"]
    assert "MARKER_AFTER_PHRASE" in message


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


def test_adapter_keeps_the_tail_of_an_overlong_failure_message():
    # pytest's longrepr puts the actual exception/assertion detail last,
    # after the file/line header and source line — cutting it down to the
    # first 500 chars keeps that header and throws away the real reason.
    result = run_adapter(LONG_MESSAGE_FIXTURE)
    assert result["failed"] == 1
    message = result["failures"][0]["message"]
    assert len(message) <= 500
    assert "REAL_REASON_AT_THE_END" in message


def test_adapter_reports_failure_when_a_fixture_raises_during_setup():
    # A fixture that raises during setup produces a per-test "error"
    # outcome (distinct from a full collection interrupt) — pytest exits 1
    # and pytest-json-report's summary carries an "error" count for it.
    # The adapter's `if errors:` branch is what's meant to catch this.
    result = run_adapter(SETUP_ERROR_FIXTURE)
    assert result["passed"] == 0
    assert result["failed"] >= 1


def test_adapter_falls_back_to_path_pytest_when_project_venv_pytest_is_unusable(tmp_path):
    # e.g. a macOS .venv bind-mounted into a Linux container: the file
    # exists but its shebang interpreter doesn't, so exec raises OSError.
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    broken = tmp_path / ".venv" / "bin" / "pytest"
    broken.parent.mkdir(parents=True)
    broken.write_text("#!/nonexistent/python\n")
    broken.chmod(0o755)

    proc = subprocess.run(
        [str(ADAPTER), "test_ok.py", str(tmp_path)], capture_output=True, text=True
    )
    result = json.loads(proc.stdout)

    assert result["passed"] == 1
    assert result["failed"] == 0
