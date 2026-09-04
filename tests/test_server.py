import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core.server import TDDServer

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_server(tmp_path):
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps(
            {
                "adapterPath": str(
                    PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh"
                )
            }
        )
    )
    return TDDServer(project_root=str(tmp_path), config_path=str(config_path))


def call(server, name, **arguments):
    result = server.call_tool(name, arguments)
    return json.loads(result[0].text)


def test_unknown_tool_returns_error_without_raising(tmp_path):
    server = make_server(tmp_path)
    payload = call(server, "not_a_real_tool")
    assert payload == {"error": "Unknown tool: not_a_real_tool"}


def test_missing_required_argument_returns_clear_error(tmp_path):
    server = make_server(tmp_path)
    payload = call(server, "init_feature", featureName="f")  # missing testFile
    assert payload["error"] == "Missing required argument: 'testFile'"


def test_phase_error_returns_clear_error_without_raising(tmp_path):
    server = make_server(tmp_path)
    call(server, "init_feature", featureName="f", testFile="tests/test_x.py")
    payload = call(server, "write_code", filePath="f.py", code="...")
    assert "only allowed in IMPLEMENT phase" in payload["error"]


def test_no_active_feature_returns_clear_error_without_raising(tmp_path):
    server = make_server(tmp_path)
    payload = call(server, "write_test", testName="t", code="...")
    assert payload["error"] == "No active feature. Call init_feature() first."


def test_init_feature_returns_status_via_call_tool(tmp_path):
    server = make_server(tmp_path)
    payload = call(server, "init_feature", featureName="f", testFile="tests/test_x.py")
    assert payload["featureName"] == "f"
    assert payload["testFile"] == "tests/test_x.py"
    assert payload["phase"] == "red"


def test_run_tests_uses_active_test_file_not_default_test_dir(tmp_path):
    # defaultTestDir is only ever consulted when no test_file is set on the
    # state machine — but call_tool's run_tests always has an active
    # feature (checked via self.sm.phase is None first). Point
    # defaultTestDir at a fixture that would fail, and the actual test
    # target at one that passes, to prove defaultTestDir has zero effect
    # while a feature is active.
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps(
            {
                "adapterPath": str(
                    PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh"
                ),
                "defaultTestDir": "tests/fixtures/broken_import_module.py",
            }
        )
    )
    server = TDDServer(project_root=str(PROJECT_ROOT), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="tests/test_state_machine.py")

    payload = call(server, "run_tests")

    assert payload["testResult"]["failed"] == 0
    assert payload["testResult"]["passed"] > 0


def test_init_feature_returns_clear_error_when_adapter_path_does_not_exist(tmp_path):
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps({"adapterPath": str(tmp_path / "no-such-adapter.sh")})
    )
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))

    payload = call(server, "init_feature", featureName="f", testFile="tests/test_x.py")

    assert "no-such-adapter.sh" in payload["error"]
    # init_feature must not have gone through — a bad adapterPath should be
    # caught before any feature state is created.
    status = call(server, "get_status")
    assert status["featureName"] is None


def test_refactor_closing_cycle_also_checks_full_suite_for_regressions(tmp_path):
    # A base-level feature whose own target already passes, but where the
    # configured defaultTestDir (the "whole suite") is currently broken.
    # Closing the REFACTOR cycle must not advance back to RED / bump
    # cycle_count while something else is broken — otherwise
    # complete_feature() becomes reachable on top of a regression.
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps(
            {
                "adapterPath": str(
                    PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh"
                ),
                "defaultTestDir": "tests/fixtures/broken_import_module.py",
            }
        )
    )
    server = TDDServer(project_root=str(PROJECT_ROOT), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="tests/test_state_machine.py")

    # test_state_machine.py already passes -> red skips straight to verify_green
    payload = call(server, "run_tests")
    assert payload["phase"] == "verify_green"
    call(server, "verify")  # -> refactor

    payload = call(server, "run_tests")

    assert payload["phase"] == "refactor"
    assert payload["cycleCount"] == 0
    assert payload["testResult"]["failed"] >= 1
