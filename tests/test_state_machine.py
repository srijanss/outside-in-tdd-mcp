import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core.state_machine import (
    InvalidTargetFilesError,
    NoActiveFeatureError,
    PhaseError,
    TDDStateMachine,
)


def make_sm(target_files=()):
    """The base level always starts with target_files=[] (init_feature's
    hard rule -- it never owns implementation files directly). When a
    real target_files is requested, drill into a nested level that owns
    it instead, since only drill_down() can ever declare real files; the
    returned sm's top-of-stack level then looks just like the old
    base-level one did (fresh RED phase, the requested target_files),
    just one level deeper.
    """
    sm = TDDStateMachine()
    sm.init_feature("feature", "tests/test_x.py", [])
    if target_files:
        to_implement(sm)
        sm.drill_down("tests/test_x.py", list(target_files))
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


def test_init_feature_blocked_when_feature_already_active():
    sm = make_sm()
    with pytest.raises(PhaseError):
        sm.init_feature("other feature", "tests/test_y.py", ["g.py"])
    # original feature/state untouched
    assert sm.feature_name == "feature"
    assert sm.test_file == "tests/test_x.py"


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


def test_failing_rerun_at_verify_green_returns_to_implement():
    sm = to_implement(make_sm())
    sm.record_test_result(passed=1, failed=0)  # implement -> verify_green
    sm.record_test_result(passed=0, failed=1)  # rerun contradicts green
    assert sm.phase == "implement"
    with pytest.raises(PhaseError):
        sm.verify()


def test_passing_rerun_at_verify_red_moves_to_verify_green():
    sm = make_sm()
    sm.record_test_result(passed=0, failed=1)  # red -> verify_red
    sm.record_test_result(passed=1, failed=0)  # rerun contradicts red
    assert sm.phase == "verify_green"


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


def test_refactor_stays_and_surfaces_error_on_zero_tests_run():
    sm = make_sm()
    to_refactor(sm)
    sm.record_test_result(passed=0, failed=0)  # refactor, no tests collected
    assert sm.phase == "refactor"
    assert sm.cycle_count == 0
    assert sm.last_error is not None


def test_write_test_only_allowed_in_red():
    sm = make_sm()
    sm.write_test("test_x")  # ok in red
    to_implement(sm)
    with pytest.raises(PhaseError):
        sm.write_test("test_x")


def test_write_test_skeleton_only_allowed_in_red():
    sm = make_sm()
    sm.write_test_skeleton("test_x")  # ok in red
    to_implement(sm)
    with pytest.raises(PhaseError):
        sm.write_test_skeleton("test_x")


def test_write_code_only_allowed_in_implement():
    sm = make_sm(target_files=["f.py"])
    with pytest.raises(PhaseError):
        sm.write_code("f.py")  # blocked in red
    to_implement(sm)
    sm.write_code("f.py")  # ok


def test_write_code_blocked_in_verify_green_and_refactor():
    sm = make_sm(target_files=["f.py"])
    sm.record_test_result(passed=1, failed=0)  # -> verify_green
    with pytest.raises(PhaseError):
        sm.write_code("f.py")
    sm.verify()  # -> refactor
    with pytest.raises(PhaseError):
        sm.write_code("f.py")


def test_write_code_blocked_for_file_outside_declared_targets():
    sm = make_sm(target_files=["f.py"])
    to_implement(sm)
    with pytest.raises(PhaseError, match="declared target files"):
        sm.write_code("other.py")  # not declared -> must drill_down first
    sm.write_code("f.py")  # declared target still allowed


def test_write_code_allowed_for_any_declared_target_in_a_set():
    sm = make_sm(target_files=["a.py", "b.py"])
    to_implement(sm)
    sm.write_code("a.py")
    sm.write_code("b.py")


def test_write_code_blocked_for_new_file_not_declared_even_if_it_does_not_exist_yet():
    # The gate is purely structural (declared targetFiles), not based on
    # whether the file already exists on disk -- new-file creation is
    # exactly the case this must catch.
    sm = make_sm(target_files=["views.py"])
    to_implement(sm)
    with pytest.raises(PhaseError):
        sm.write_code("new_module.py")


def test_drill_down_scopes_write_code_to_its_own_declared_targets():
    sm = make_sm(target_files=["views.py"])
    to_implement(sm)
    sm.drill_down("cart/tests.py", ["cart/models.py"])
    sm.write_test("test_cart")
    sm.record_test_result(passed=0, failed=1)
    sm.verify()  # nested -> implement
    with pytest.raises(PhaseError):
        sm.write_code("views.py")  # parent's target, not this level's
    sm.write_code("cart/models.py")  # this level's own declared target


def test_init_feature_rejects_any_non_empty_target_files():
    # The base level never owns implementation files directly -- whether
    # testFile is an acceptance test, a unit test, or a refactor-only
    # feature -- so a non-empty list must be rejected unconditionally,
    # regardless of whether it's otherwise well-formed. This isn't left to
    # the caller's judgment about what "kind" of test testFile is.
    sm = TDDStateMachine()
    with pytest.raises(InvalidTargetFilesError, match="must be empty"):
        sm.init_feature("f", "tests/test_x.py", ["f.py"])
    with pytest.raises(InvalidTargetFilesError, match="must be empty"):
        sm.init_feature("f", "tests/test_x.py", ("a.py", "b.py"))
    # empty list still works
    sm.init_feature("f", "tests/test_x.py", [])
    assert sm.target_files == ()

    # empty tuple still works too (on a fresh instance -- the one above
    # already has an active feature)
    sm2 = TDDStateMachine()
    sm2.init_feature("f", "tests/test_x.py", ())
    assert sm2.target_files == ()


def test_module_docstring_does_not_claim_init_feature_sets_target_files():
    # init_feature() now always forces target_files=[] -- only drill_down()
    # ever declares real implementation files. The module docstring must
    # not claim otherwise.
    docstring = Path(__file__).resolve().parents[1] / "core" / "state_machine.py"
    text = docstring.read_text()
    module_doc = " ".join(text.split('"""')[1].split())
    assert "set by init_feature()/drill_down()" not in module_doc
    assert "drill_down()" in module_doc


def test_init_feature_and_drill_down_reject_non_list_or_non_string_target_files():
    # target_files arrives from the MCP call boundary with no guarantee of
    # shape -- a bad value (a bare string, or a list with non-string
    # entries) must be rejected clearly, not silently misinterpreted (e.g.
    # tuple("file.py") turning into per-character targets) or left to
    # crash later inside write_code()'s error path.
    sm = TDDStateMachine()
    with pytest.raises(InvalidTargetFilesError):
        sm.init_feature("f", "tests/test_x.py", "not_a_list.py")
    with pytest.raises(InvalidTargetFilesError):
        sm.init_feature("f", "tests/test_x.py", [1, 2])
    # a valid call still works after the rejected ones
    sm.init_feature("f", "tests/test_x.py", [])

    to_implement(sm)
    with pytest.raises(InvalidTargetFilesError):
        sm.drill_down("cart/tests.py", "cart/models.py")
    with pytest.raises(InvalidTargetFilesError):
        sm.drill_down("cart/tests.py", [None])
    sm.drill_down("cart/tests.py", ["cart/models.py"])  # still works


def test_invalid_target_files_error_message_mentions_tuple_too():
    # The validator accepts both list and tuple -- the rejection message
    # for a wrong-type value (not a bare string, not a list/tuple at all)
    # must say so, not just "list of strings".
    sm = TDDStateMachine()
    with pytest.raises(InvalidTargetFilesError, match="list or tuple of strings"):
        sm.init_feature("f", "tests/test_x.py", {"not": "a list"})


def test_init_feature_and_drill_down_reject_none_target_files():
    sm = TDDStateMachine()
    with pytest.raises(InvalidTargetFilesError):
        sm.init_feature("f", "tests/test_x.py", None)
    sm.init_feature("f", "tests/test_x.py", [])

    to_implement(sm)
    with pytest.raises(InvalidTargetFilesError):
        sm.drill_down("cart/tests.py", None)
    sm.drill_down("cart/tests.py", ["cart/models.py"])  # still works


def test_init_feature_rejects_non_list_tuple_iterables():
    # A generator or dict is iterable but isn't the list/tuple shape the
    # contract promises -- must be rejected the same as a bare string,
    # not silently accepted because it happens to support iteration.
    sm = TDDStateMachine()
    with pytest.raises(InvalidTargetFilesError):
        sm.init_feature("f", "tests/test_x.py", {"f.py": 1})
    with pytest.raises(InvalidTargetFilesError):
        sm.init_feature("g", "tests/test_x.py", (f for f in ["f.py"]))


def test_init_feature_rejects_mixed_string_and_non_string_target_files():
    sm = TDDStateMachine()
    with pytest.raises(InvalidTargetFilesError):
        sm.init_feature("f", "tests/test_x.py", ["a.py", 1])


def test_init_feature_and_drill_down_reject_empty_or_whitespace_target_files():
    # An empty string or whitespace-only string isn't a meaningful file
    # path -- it would never match a real write_code() call, so it should
    # be rejected upfront rather than silently accepted as a dead entry.
    # (Only exercised via drill_down now -- init_feature's target_files is
    # always [], so these malformed non-empty entries never reach it.)
    sm = TDDStateMachine()
    sm.init_feature("f", "tests/test_x.py", [])

    to_implement(sm)
    with pytest.raises(InvalidTargetFilesError):
        sm.drill_down("cart/tests.py", [""])
    with pytest.raises(InvalidTargetFilesError):
        sm.drill_down("cart/tests.py", ["  "])
    sm.drill_down("cart/tests.py", ["cart/models.py"])  # still works


def test_init_feature_and_drill_down_reject_duplicate_target_files():
    # A duplicate entry is either a copy-paste mistake or a sign the caller
    # doesn't actually know what it's declaring -- reject it rather than
    # silently collapsing it, so the mistake is visible immediately.
    # (Only exercised via drill_down now -- init_feature's target_files is
    # always [], so a duplicate-entries list never reaches it.)
    sm = TDDStateMachine()
    sm.init_feature("f", "tests/test_x.py", [])

    to_implement(sm)
    with pytest.raises(InvalidTargetFilesError):
        sm.drill_down("cart/tests.py", ["cart/models.py", "cart/models.py"])
    sm.drill_down("cart/tests.py", ["cart/models.py"])  # still works


def test_drill_down_accepts_tuple_of_strings():
    # The validator explicitly allows tuples, not just lists -- must
    # actually be exercised, not just permitted by the isinstance check.
    # (Only exercised via drill_down now -- init_feature's target_files is
    # always [].)
    sm = TDDStateMachine()
    sm.init_feature("f", "tests/test_x.py", [])
    to_implement(sm)
    sm.drill_down("cart/tests.py", ("a.py", "b.py"))
    to_implement(sm)
    sm.write_code("a.py")
    sm.drill_down("cart/tests.py", ("cart/models.py",))
    sm.write_test("test_cart")
    sm.record_test_result(passed=0, failed=1)
    sm.verify()
    sm.write_code("cart/models.py")


def test_empty_target_files_blocks_all_write_code_at_that_level():
    # An empty targetFiles list is a legitimate (if unusual) declaration --
    # it means this level owns nothing to write directly, so every
    # write_code() call must be blocked until a drill_down declares an
    # actual target. Applies the same way to a drilled-down level.
    sm = make_sm(target_files=[])
    to_implement(sm)
    with pytest.raises(PhaseError, match="declared target files"):
        sm.write_code("anything.py")

    sm2 = make_sm(target_files=["f.py"])
    to_implement(sm2)
    sm2.drill_down("cart/tests.py", [])
    sm2.write_test("test_cart")
    sm2.record_test_result(passed=0, failed=1)
    sm2.verify()  # nested -> implement
    with pytest.raises(PhaseError, match="declared target files"):
        sm2.write_code("cart/models.py")


def test_write_code_error_message_handles_non_string_target_files():
    # init_feature/drill_down now reject non-string target_files upfront,
    # but the error-formatting code in write_code() is a second line of
    # defense against internal state ever holding non-strings -- it must
    # not itself crash with a raw TypeError from str.join() in that case.
    sm = make_sm(target_files=["f.py"])
    to_implement(sm)
    sm.stack[-1].target_files = (1, 2, 3)
    with pytest.raises(PhaseError, match="declared target files"):
        sm.write_code("other.py")


def test_write_code_error_message_handles_file_path_with_single_quote():
    # The error message suggests a drill_down(...) snippet quoting file_path
    # with a literal single-quote wrap -- a file_path containing its own
    # single quote must not produce a broken-looking suggestion (e.g.
    # targetFiles=['fo'o.py']). Use repr() so it's always valid Python.
    sm = make_sm(target_files=["f.py"])
    to_implement(sm)
    with pytest.raises(PhaseError) as exc_info:
        sm.write_code("fo'o.py")
    assert repr("fo'o.py") in str(exc_info.value)
    assert "['fo'o.py']" not in str(exc_info.value)


def test_write_code_target_matching_is_exact_no_path_normalization():
    # write_code()'s membership check is a plain string comparison, by
    # design -- no normalization of "./f.py" vs "f.py", trailing slashes,
    # etc. Locked in here so the exact-match contract stays a deliberate,
    # documented choice rather than an accidental one that silently
    # changes later.
    sm = make_sm(target_files=["f.py"])
    to_implement(sm)
    with pytest.raises(PhaseError, match="declared target files"):
        sm.write_code("./f.py")
    sm.write_code("f.py")  # exact match still works


def test_refactor_code_only_allowed_in_refactor():
    sm = make_sm()
    with pytest.raises(PhaseError):
        sm.refactor_code("cleanup")
    to_refactor(sm)
    sm.refactor_code("cleanup")  # ok


def test_no_active_feature_raises():
    sm = TDDStateMachine()
    with pytest.raises(NoActiveFeatureError):
        sm.write_test("x")
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


def test_reset_feature_clears_review_finding_without_marking_it_fixed():
    sm = TDDStateMachine()
    sm.init_feature(
        "feature",
        "tests/test_x.py",
        [],
        review_finding={"id": "missing-lock", "scope": "diff:uncommitted"},
    )
    sm.reset_feature()
    assert sm.review_finding is None


def test_drill_down_only_allowed_in_implement():
    sm = make_sm()
    with pytest.raises(PhaseError):
        sm.drill_down("cart/tests.py", ["cart/models.py"])  # blocked in red
    to_implement(sm)
    sm.drill_down("cart/tests.py", ["cart/models.py"])  # ok
    assert sm.depth == 2
    assert sm.test_file == "cart/tests.py"
    assert sm.phase == "red"


def test_drill_down_nested_level_runs_independent_cycle():
    sm = make_sm()
    to_implement(sm)
    sm.drill_down("cart/tests.py", ["cart/models.py"])
    sm.write_test("test_cart")  # allowed: nested level is in red
    sm.record_test_result(passed=0, failed=1)  # nested red -> verify_red
    sm.verify()  # nested verify_red -> implement
    assert sm.depth == 2
    assert sm.phase == "implement"
    sm.write_code("cart/models.py")  # nested level's own implement
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
    sm.drill_down("cart/tests.py", ["cart/models.py"])
    with pytest.raises(PhaseError):
        sm.return_to_parent()  # nested level still in red, cycle_count 0
    sm.record_test_result(passed=1, failed=0)  # nested red -> verify_green
    with pytest.raises(PhaseError):
        sm.return_to_parent()  # nested still not back in red


def test_return_to_parent_blocked_after_new_nested_test_declared():
    sm = make_sm()
    to_implement(sm)
    sm.drill_down("cart/tests.py", ["cart/models.py"])
    to_red_after_one_cycle(sm)  # nested cycle 1 closed
    sm.write_test("test_next_nested_behavior")  # nested cycle 2 started
    with pytest.raises(PhaseError):
        sm.return_to_parent()


def test_return_to_parent_pops_and_resumes_parent_implement():
    # "parent" here is itself a drilled-down level (owning f.py) since the
    # true base level can never own real target_files -- what matters is
    # the relative depth change across drill_down/return_to_parent, not
    # the absolute stack size.
    sm = make_sm(target_files=["f.py"])
    to_implement(sm)
    parent_depth = sm.depth
    sm.drill_down("cart/tests.py", ["cart/models.py"])
    to_red_after_one_cycle(sm)  # nested: red -> ... -> red, cycle 1
    assert sm.depth == parent_depth + 1

    summary = sm.return_to_parent()
    assert summary == {"testFile": "cart/tests.py", "cyclesCompleted": 1}
    assert sm.depth == parent_depth
    assert sm.phase == "implement"  # resumed exactly where the parent was
    assert sm.test_file == "tests/test_x.py"
    sm.write_code("f.py")  # parent's implement still works


def test_abandon_drill_down_blocked_at_base_level():
    sm = make_sm()
    with pytest.raises(PhaseError):
        sm.abandon_drill_down()  # depth == 1


def test_abandon_drill_down_pops_regardless_of_phase_or_cycle_count():
    sm = make_sm()
    to_implement(sm)
    sm.drill_down("cart/tests.py", ["cart/models.py"])  # nested level: red, cycle_count 0
    summary = sm.abandon_drill_down()  # no cycle finished yet — still pops
    assert summary == {"testFile": "cart/tests.py", "phase": "red", "cycleCount": 0}
    assert sm.depth == 1
    assert sm.phase == "implement"  # parent resumed untouched
    assert sm.test_file == "tests/test_x.py"


def test_abandon_drill_down_pops_mid_implement_too():
    sm = make_sm()
    to_implement(sm)
    sm.drill_down("cart/tests.py", ["cart/models.py"])
    sm.record_test_result(passed=0, failed=1)  # nested red -> verify_red
    sm.verify()  # nested verify_red -> implement
    summary = sm.abandon_drill_down()
    assert summary["phase"] == "implement"
    assert sm.depth == 1
    assert sm.phase == "implement"


def test_multiple_drill_downs_across_different_apps():
    sm = make_sm()
    to_implement(sm)
    sm.drill_down("cart/tests.py", ["cart/models.py"])
    to_red_after_one_cycle(sm)
    sm.return_to_parent()
    assert sm.depth == 1 and sm.phase == "implement"

    sm.drill_down("orders/tests.py", ["orders/models.py"])
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
    sm.drill_down("cart/tests.py", ["cart/models.py"])
    to_red_after_one_cycle(sm)  # nested level is red, cycle_count 1 — but not base
    with pytest.raises(PhaseError):
        sm.complete_feature()
    sm.return_to_parent()  # back to depth 1, implement
    assert sm.depth == 1


def test_complete_feature_blocked_after_new_test_declared():
    sm = make_sm()
    to_red_after_one_cycle(sm)  # cycle 1 closed
    sm.write_test("test_next_behavior")  # cycle 2 started, never run
    sm = TDDStateMachine.from_dict(sm.to_dict())  # survives a restart
    with pytest.raises(PhaseError):
        sm.complete_feature()


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
        "reviewFinding": None,
    }
    assert sm.phase is None
    assert sm.feature_name is None
    assert sm.cycle_count == 0


def test_complete_feature_returns_the_linked_review_finding():
    sm = TDDStateMachine()
    sm.init_feature(
        "feature",
        "tests/test_x.py",
        [],
        review_finding={"id": "missing-lock", "scope": "diff:uncommitted"},
    )
    to_red_after_one_cycle(sm)

    summary = sm.complete_feature()

    assert summary["reviewFinding"] == {
        "id": "missing-lock",
        "scope": "diff:uncommitted",
    }


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
    assert "verify" in sm.available_tools()


def test_missing_symbol_failure_sets_stub_only_hint_through_implement():
    sm = make_sm()
    sm.record_test_result(
        passed=0,
        failed=1,
        failures=[
            {"name": "t", "message": "ImportError: cannot import name 'Foo'"}
        ],
    )  # red -> verify_red
    assert sm.last_error is not None
    assert "stub" in sm.last_error.lower()

    sm.verify()  # verify_red -> implement
    assert sm.phase == "implement"
    assert sm.last_error is not None  # hint survives the verify() checkpoint


def test_real_assertion_failure_does_not_set_stub_only_hint():
    sm = to_implement(make_sm())
    sm.record_test_result(
        passed=0,
        failed=1,
        failures=[{"name": "t", "message": "AssertionError: expected True"}],
    )
    assert sm.phase == "implement"
    assert sm.last_error is None


def test_missing_symbol_failure_from_a_mock_based_test_does_not_set_stub_only_hint():
    # A stub can never satisfy a test that asserts on calls made to a mock,
    # so the "write only a stub" nudge would be actively misleading here.
    sm = make_sm()
    sm.record_test_result(
        passed=0,
        failed=1,
        failures=[
            {
                "name": "t",
                "message": (
                    "  File \"/usr/lib/python3.12/unittest/mock.py\", line 1450, "
                    "in __enter__\n"
                    "AttributeError: <module 'svc'> has no attribute 'notify'"
                ),
            }
        ],
    )
    assert sm.phase == "verify_red"
    assert sm.last_error is None


def test_stub_only_hint_clears_once_a_later_run_reports_a_real_failure():
    sm = make_sm()
    sm.record_test_result(
        passed=0,
        failed=1,
        failures=[{"name": "t", "message": "NameError: name 'Foo' is not defined"}],
    )
    sm.verify()
    assert sm.last_error is not None

    sm.record_test_result(
        passed=0,
        failed=1,
        failures=[{"name": "t", "message": "AssertionError: expected True"}],
    )
    assert sm.last_error is None


def test_from_dict_round_trip_preserves_review_finding():
    sm = TDDStateMachine()
    sm.init_feature(
        "feature",
        "tests/test_x.py",
        [],
        review_finding={"id": "missing-lock", "scope": "diff:uncommitted"},
    )

    restored = TDDStateMachine.from_dict(sm.to_dict())

    assert restored.review_finding == {
        "id": "missing-lock",
        "scope": "diff:uncommitted",
    }


def test_from_dict_ignores_a_malformed_review_finding_instead_of_crashing():
    sm = TDDStateMachine()
    sm.init_feature("feature", "tests/test_x.py", [])
    data = sm.to_dict()
    data["reviewFinding"] = {"id": "missing-lock"}  # missing "scope"

    restored = TDDStateMachine.from_dict(data)

    assert restored.review_finding is None


def test_from_dict_ignores_a_review_finding_with_wrong_typed_fields():
    sm = TDDStateMachine()
    sm.init_feature("feature", "tests/test_x.py", [])
    data = sm.to_dict()
    data["reviewFinding"] = {"id": 123, "scope": "diff:uncommitted"}

    restored = TDDStateMachine.from_dict(data)

    assert restored.review_finding is None


def test_from_dict_preserves_valid_levels_up_to_first_malformed_entry():
    # A corrupted on-disk state file shouldn't wipe an entire multi-level
    # drill-down stack just because one entry (e.g. the newest, half-written
    # one) is bad -- the levels below it are still trustworthy and should
    # survive.
    valid_level_1 = {
        "testFile": "tests/test_x.py",
        "targetFiles": [],
        "phase": "implement",
        "cycleCount": 0,
        "lastError": None,
        "lastResult": None,
    }
    valid_level_2 = {
        "testFile": "views_test.py",
        "targetFiles": ["views.py"],
        "phase": "red",
        "cycleCount": 0,
        "lastError": None,
        "lastResult": None,
    }
    malformed_level_3 = {
        "testFile": "broken.py",
        "targetFiles": [],
        "phase": "not-a-real-phase",
        "cycleCount": 0,
    }
    data = {
        "featureName": "feature",
        "stack": [valid_level_1, valid_level_2, malformed_level_3],
    }

    sm = TDDStateMachine.from_dict(data)

    assert sm.feature_name == "feature"
    assert sm.depth == 2
    assert sm.test_file == "views_test.py"
    assert sm.target_files == ("views.py",)
