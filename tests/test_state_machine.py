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


def to_implement(sm):
    sm.record_test_result(passed=0, failed=1)  # red -> verify_red
    sm.verify()  # verify_red -> implement
    return sm


def to_refactor(sm):
    sm.record_test_result(passed=1, failed=0)  # red -> verify_green
    sm.verify()  # verify_green -> refactor
    return sm


def to_red_after_one_cycle(sm):
    to_refactor(sm)
    sm.record_test_result(passed=1, failed=0)  # refactor -> red, cycle 1
    return sm


def test_init_feature_starts_in_red():
    sm = make_sm()
    assert sm.phase == "red"
    assert sm.feature_name == "feature"
    assert sm.test_file == "tests/test_x.py"
    assert sm.cycle_count == 0


def test_red_moves_to_verify_red_on_failure_and_verify_advances_to_implement():
    sm = make_sm()
    sm.record_test_result(passed=0, failed=1)
    assert sm.phase == "verify_red"
    sm.verify()
    assert sm.phase == "implement"


def test_implement_stays_on_failure():
    sm = make_sm()
    to_implement(sm)
    sm.record_test_result(passed=0, failed=1)
    assert sm.phase == "implement"


def test_implement_advances_to_verify_green_on_pass():
    sm = make_sm()
    to_implement(sm)
    sm.record_test_result(passed=1, failed=0)  # implement -> verify_green
    assert sm.phase == "verify_green"


def test_red_skips_directly_to_verify_green_if_already_passing():
    sm = make_sm()
    sm.record_test_result(passed=1, failed=0)
    assert sm.phase == "verify_green"


def test_verify_green_advances_to_refactor():
    sm = make_sm()
    sm.record_test_result(passed=1, failed=0)  # red -> verify_green
    sm.verify()
    assert sm.phase == "refactor"


def test_verify_only_allowed_in_verify_red_or_verify_green():
    sm = make_sm()
    with pytest.raises(PhaseError):
        sm.verify()  # blocked in red
    to_implement(sm)
    with pytest.raises(PhaseError):
        sm.verify()  # blocked in implement
    sm.record_test_result(passed=1, failed=0)  # implement -> verify_green
    sm.verify()  # ok
    assert sm.phase == "refactor"
    with pytest.raises(PhaseError):
        sm.verify()  # blocked in refactor


def test_refactor_advances_to_red_and_increments_cycle_on_pass():
    sm = make_sm()
    to_refactor(sm)
    assert sm.cycle_count == 0
    sm.record_test_result(passed=1, failed=0)  # refactor -> red
    assert sm.phase == "red"
    assert sm.cycle_count == 1


def test_refactor_stays_and_surfaces_error_on_failure():
    sm = make_sm()
    to_refactor(sm)
    sm.record_test_result(passed=0, failed=1)  # refactor, broke something
    assert sm.phase == "refactor"
    assert sm.cycle_count == 0
    assert sm.last_error is not None


def test_write_test_only_allowed_in_red():
    sm = make_sm()
    sm.write_test("test_x", "code")  # ok in red
    to_implement(sm)
    with pytest.raises(PhaseError):
        sm.write_test("test_x", "code")


def test_write_test_skeleton_only_allowed_in_red():
    sm = make_sm()
    sm.write_test_skeleton("test_x", "# TODO: cover the happy path")  # ok in red
    to_implement(sm)
    with pytest.raises(PhaseError):
        sm.write_test_skeleton("test_x", "code")


def test_write_code_only_allowed_in_implement():
    sm = make_sm()
    with pytest.raises(PhaseError):
        sm.write_code("f.py", "code")  # blocked in red
    to_implement(sm)
    sm.write_code("f.py", "code")  # ok


def test_write_code_blocked_in_verify_green_and_refactor():
    sm = make_sm()
    sm.record_test_result(passed=1, failed=0)  # -> verify_green
    with pytest.raises(PhaseError):
        sm.write_code("f.py", "code")
    sm.verify()  # -> refactor
    with pytest.raises(PhaseError):
        sm.write_code("f.py", "code")


def test_refactor_code_only_allowed_in_refactor():
    sm = make_sm()
    with pytest.raises(PhaseError):
        sm.refactor_code("cleanup")
    to_refactor(sm)
    sm.refactor_code("cleanup")  # ok


def test_no_active_feature_raises():
    sm = TDDStateMachine()
    with pytest.raises(NoActiveFeatureError):
        sm.write_test("x", "y")
    with pytest.raises(NoActiveFeatureError):
        sm.record_test_result(passed=1, failed=0)
    with pytest.raises(NoActiveFeatureError):
        sm.verify()


def test_reset_feature_clears_state():
    sm = make_sm()
    sm.record_test_result(passed=0, failed=1)
    sm.reset_feature()
    assert sm.phase is None
    assert sm.feature_name is None
    assert sm.cycle_count == 0


def test_drill_down_only_allowed_in_implement():
    sm = make_sm()
    with pytest.raises(PhaseError):
        sm.drill_down("cart/tests.py")  # blocked in red
    to_implement(sm)
    sm.drill_down("cart/tests.py")  # ok
    assert sm.depth == 2
    assert sm.test_file == "cart/tests.py"
    assert sm.phase == "red"


def test_drill_down_nested_level_runs_independent_cycle():
    sm = make_sm()
    to_implement(sm)
    sm.drill_down("cart/tests.py")
    sm.write_test("test_cart", "...")  # allowed: nested level is in red
    sm.record_test_result(passed=0, failed=1)  # nested red -> verify_red
    sm.verify()  # nested verify_red -> implement
    assert sm.depth == 2
    assert sm.phase == "implement"
    sm.write_code("cart/models.py", "...")  # nested level's own implement
    # outer level's write_code should NOT be reachable — only nested is active
    with pytest.raises(PhaseError):
        sm.refactor_code("desc")  # nested is implement, not refactor


def test_return_to_parent_blocked_at_base_level():
    sm = make_sm()
    with pytest.raises(PhaseError):
        sm.return_to_parent()  # depth == 1


def test_return_to_parent_blocked_before_nested_cycle_completes():
    sm = make_sm()
    to_implement(sm)
    sm.drill_down("cart/tests.py")
    with pytest.raises(PhaseError):
        sm.return_to_parent()  # nested level still in red, cycle_count 0
    sm.record_test_result(passed=1, failed=0)  # nested red -> verify_green
    with pytest.raises(PhaseError):
        sm.return_to_parent()  # nested still not back in red


def test_return_to_parent_pops_and_resumes_parent_implement():
    sm = make_sm()
    to_implement(sm)
    sm.drill_down("cart/tests.py")
    to_red_after_one_cycle(sm)  # nested: red -> ... -> red, cycle 1
    assert sm.depth == 2

    summary = sm.return_to_parent()
    assert summary == {"testFile": "cart/tests.py", "cyclesCompleted": 1}
    assert sm.depth == 1
    assert sm.phase == "implement"  # resumed exactly where the parent was
    assert sm.test_file == "tests/test_x.py"
    sm.write_code("f.py", "code")  # parent's implement still works


def test_abandon_drill_down_blocked_at_base_level():
    sm = make_sm()
    with pytest.raises(PhaseError):
        sm.abandon_drill_down()  # depth == 1


def test_abandon_drill_down_pops_regardless_of_phase_or_cycle_count():
    sm = make_sm()
    to_implement(sm)
    sm.drill_down("cart/tests.py")  # nested level: red, cycle_count 0
    summary = sm.abandon_drill_down()  # no cycle finished yet — still pops
    assert summary == {"testFile": "cart/tests.py", "phase": "red", "cycleCount": 0}
    assert sm.depth == 1
    assert sm.phase == "implement"  # parent resumed untouched
    assert sm.test_file == "tests/test_x.py"


def test_abandon_drill_down_pops_mid_implement_too():
    sm = make_sm()
    to_implement(sm)
    sm.drill_down("cart/tests.py")
    sm.record_test_result(passed=0, failed=1)  # nested red -> verify_red
    sm.verify()  # nested verify_red -> implement
    summary = sm.abandon_drill_down()
    assert summary["phase"] == "implement"
    assert sm.depth == 1
    assert sm.phase == "implement"


def test_multiple_drill_downs_across_different_apps():
    sm = make_sm()
    to_implement(sm)
    sm.drill_down("cart/tests.py")
    to_red_after_one_cycle(sm)
    sm.return_to_parent()
    assert sm.depth == 1 and sm.phase == "implement"

    sm.drill_down("orders/tests.py")
    assert sm.depth == 2
    assert sm.test_file == "orders/tests.py"
    to_red_after_one_cycle(sm)
    sm.return_to_parent()
    assert sm.depth == 1 and sm.phase == "implement"


def test_complete_feature_blocked_before_first_cycle():
    sm = make_sm()
    with pytest.raises(PhaseError):
        sm.complete_feature()  # red, cycle_count == 0


def test_complete_feature_blocked_outside_red():
    sm = make_sm()
    sm.record_test_result(passed=1, failed=0)  # -> verify_green
    with pytest.raises(PhaseError):
        sm.complete_feature()
    sm.verify()  # -> refactor
    with pytest.raises(PhaseError):
        sm.complete_feature()


def test_complete_feature_blocked_while_drilled_down():
    sm = make_sm()
    to_implement(sm)
    sm.drill_down("cart/tests.py")
    to_red_after_one_cycle(sm)  # nested level is red, cycle_count 1 — but not base
    with pytest.raises(PhaseError):
        sm.complete_feature()
    sm.return_to_parent()  # back to depth 1, implement
    assert sm.depth == 1


def test_complete_feature_allowed_after_full_cycle_and_clears_state():
    sm = make_sm()
    to_red_after_one_cycle(sm)  # red -> ... -> red, cycle_count=1
    assert sm.phase == "red"
    assert sm.cycle_count == 1

    summary = sm.complete_feature()
    assert summary == {
        "featureName": "feature",
        "testFile": "tests/test_x.py",
        "cyclesCompleted": 1,
    }
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
    assert sm.available_tools() == ("verify", "get_status")
    sm.verify()
    assert sm.available_tools() == ("write_code", "run_tests", "get_status")
    sm.record_test_result(passed=1, failed=0)
    assert sm.available_tools() == ("verify", "get_status")
    sm.verify()
    assert sm.available_tools() == ("refactor_code", "run_tests", "get_status")


def test_status_shape():
    sm = make_sm()
    sm.record_test_result(passed=0, failed=1, duration_ms=42, failures=[{"name": "t"}])
    status = sm.status()
    assert status["phase"] == "verify_red"
    assert status["lastResult"]["failed"] == 1
    assert status["lastResult"]["durationMs"] == 42
    assert "verify" in status["availableTools"]
