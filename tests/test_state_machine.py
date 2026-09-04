import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core.state_machine import (
    NoActiveFeatureError,
    PhaseError,
    TDDStateMachine,
)


def make_sm():
    sm = TDDStateMachine()
    sm.init_feature("feature", "tests/test_x.py")
    return sm


def test_init_feature_starts_in_red():
    sm = make_sm()
    assert sm.phase == "red"
    assert sm.feature_name == "feature"
    assert sm.test_file == "tests/test_x.py"
    assert sm.cycle_count == 0


def test_red_moves_to_implement_on_failure_then_implement_stays_on_failure():
    sm = make_sm()
    sm.record_test_result(passed=0, failed=1)
    assert sm.phase == "implement"
    sm.record_test_result(passed=0, failed=1)
    assert sm.phase == "implement"


def test_implement_advances_to_green_on_pass():
    sm = make_sm()
    sm.record_test_result(passed=0, failed=1)  # red -> implement
    sm.record_test_result(passed=1, failed=0)  # implement -> green
    assert sm.phase == "green"


def test_red_skips_directly_to_green_if_already_passing():
    sm = make_sm()
    sm.record_test_result(passed=1, failed=0)
    assert sm.phase == "green"


def test_green_advances_to_refactor_unconditionally():
    sm = make_sm()
    sm.record_test_result(passed=1, failed=0)  # red -> green
    sm.record_test_result(passed=1, failed=0)  # green -> refactor
    assert sm.phase == "refactor"


def test_refactor_advances_to_red_and_increments_cycle_on_pass():
    sm = make_sm()
    sm.record_test_result(passed=1, failed=0)  # red -> green
    sm.record_test_result(passed=1, failed=0)  # green -> refactor
    assert sm.cycle_count == 0
    sm.record_test_result(passed=1, failed=0)  # refactor -> red
    assert sm.phase == "red"
    assert sm.cycle_count == 1


def test_refactor_stays_and_surfaces_error_on_failure():
    sm = make_sm()
    sm.record_test_result(passed=1, failed=0)  # red -> green
    sm.record_test_result(passed=1, failed=0)  # green -> refactor
    sm.record_test_result(passed=0, failed=1)  # refactor, broke something
    assert sm.phase == "refactor"
    assert sm.cycle_count == 0
    assert sm.last_error is not None


def test_write_test_only_allowed_in_red():
    sm = make_sm()
    sm.write_test("test_x", "code")  # ok in red
    sm.record_test_result(passed=0, failed=1)  # -> implement
    with pytest.raises(PhaseError):
        sm.write_test("test_x", "code")


def test_write_code_only_allowed_in_implement():
    sm = make_sm()
    with pytest.raises(PhaseError):
        sm.write_code("f.py", "code")  # blocked in red
    sm.record_test_result(passed=0, failed=1)  # -> implement
    sm.write_code("f.py", "code")  # ok


def test_write_code_blocked_in_green_and_refactor():
    sm = make_sm()
    sm.record_test_result(passed=1, failed=0)  # -> green
    with pytest.raises(PhaseError):
        sm.write_code("f.py", "code")
    sm.record_test_result(passed=1, failed=0)  # -> refactor
    with pytest.raises(PhaseError):
        sm.write_code("f.py", "code")


def test_refactor_code_only_allowed_in_refactor():
    sm = make_sm()
    with pytest.raises(PhaseError):
        sm.refactor_code("cleanup")
    sm.record_test_result(passed=1, failed=0)  # -> green
    sm.record_test_result(passed=1, failed=0)  # -> refactor
    sm.refactor_code("cleanup")  # ok


def test_no_active_feature_raises():
    sm = TDDStateMachine()
    with pytest.raises(NoActiveFeatureError):
        sm.write_test("x", "y")
    with pytest.raises(NoActiveFeatureError):
        sm.record_test_result(passed=1, failed=0)


def test_reset_feature_clears_state():
    sm = make_sm()
    sm.record_test_result(passed=0, failed=1)
    sm.reset_feature()
    assert sm.phase is None
    assert sm.feature_name is None
    assert sm.cycle_count == 0


def test_available_tools_per_phase():
    sm = make_sm()
    assert sm.available_tools() == (
        "write_test",
        "run_tests",
        "get_status",
        "init_feature",
    )
    sm.record_test_result(passed=0, failed=1)
    assert sm.available_tools() == ("write_code", "run_tests", "get_status")
    sm.record_test_result(passed=1, failed=0)
    assert sm.available_tools() == ("run_tests", "get_status")
    sm.record_test_result(passed=1, failed=0)
    assert sm.available_tools() == ("refactor_code", "run_tests", "get_status")


def test_status_shape():
    sm = make_sm()
    sm.record_test_result(passed=0, failed=1, duration_ms=42, failures=[{"name": "t"}])
    status = sm.status()
    assert status["phase"] == "implement"
    assert status["lastResult"]["failed"] == 1
    assert status["lastResult"]["durationMs"] == 42
    assert "write_code" in status["availableTools"]
