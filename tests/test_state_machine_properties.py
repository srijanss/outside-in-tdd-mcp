"""Property-based action-sequence tests for TDDStateMachine.

The example-based tests in test_state_machine.py pin down one scenario
each; the bugs they missed (contradictory checkpoint reruns, completing
with a newly declared test pending) only showed up in particular action
orders. This drives random sequences of every public action and checks
the workflow's invariants after each step.
"""

import json

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)

from core.state_machine import (
    PHASES,
    InvalidTargetFilesError,
    NoActiveFeatureError,
    PhaseError,
    TDDStateMachine,
)

REJECTIONS = (PhaseError, NoActiveFeatureError, InvalidTargetFilesError)
TARGETS = ("a.py", "b.py", "c.py")
counts = st.integers(min_value=0, max_value=3)


class TDDWorkflow(RuleBasedStateMachine):
    @initialize()
    def start(self):
        # Start mid-feature: from an empty machine almost every action is
        # rejected, so short runs would barely exercise the workflow.
        self.sm = TDDStateMachine()
        self.sm.init_feature("feature", "tests/test_f.py", [])

    def attempt(self, action, *args):
        """Run one action; a rejected action must leave state untouched.
        Returns the pre-action snapshot, or None if it was rejected."""
        before = self.sm.to_dict()
        try:
            action(*args)
        except REJECTIONS:
            assert self.sm.to_dict() == before, f"{action.__name__} mutated state"
            return None
        return before

    # -- lifecycle -----------------------------------------------------

    @rule()
    def init_feature(self):
        had_feature = self.sm.depth > 0
        before = self.attempt(self.sm.init_feature, "feature", "tests/test_f.py", [])
        assert (before is None) == had_feature
        if before is not None:
            assert (self.sm.depth, self.sm.phase, self.sm.cycle_count) == (1, "red", 0)

    @rule()
    def reset_feature(self):
        self.sm.reset_feature()
        assert self.sm.depth == 0 and self.sm.feature_name is None

    @rule()
    def complete_feature(self):
        before = self.attempt(self.sm.complete_feature)
        if before is not None:
            (base,) = before["stack"]
            assert base["phase"] == "red"
            assert base["cycleCount"] >= 1
            assert base["testDeclared"] is False
            assert self.sm.depth == 0

    @rule(target_files=st.lists(st.sampled_from(TARGETS), min_size=1, max_size=2,
                                unique=True))
    def drill_down(self, target_files):
        before = self.attempt(self.sm.drill_down, "tests/test_nested.py", target_files)
        if before is not None:
            assert before["stack"][-1]["phase"] == "implement"
            assert self.sm.to_dict()["stack"][:-1] == before["stack"]
            assert (self.sm.phase, self.sm.cycle_count) == ("red", 0)

    @rule()
    def return_to_parent(self):
        before = self.attempt(self.sm.return_to_parent)
        if before is not None:
            top = before["stack"][-1]
            assert len(before["stack"]) >= 2
            assert top["phase"] == "red"
            assert top["cycleCount"] >= 1
            assert top["testDeclared"] is False
            # The parent resumes exactly where it was left.
            assert self.sm.to_dict()["stack"] == before["stack"][:-1]

    @rule()
    def abandon_drill_down(self):
        before = self.attempt(self.sm.abandon_drill_down)
        if before is not None:
            assert self.sm.to_dict()["stack"] == before["stack"][:-1]

    # -- gated actions ---------------------------------------------------

    @rule()
    def write_test(self):
        before = self.attempt(self.sm.write_test, "test_x")
        if before is not None:
            assert before["stack"][-1]["phase"] in ("red", "verify_red")
            assert self.sm.test_declared

    @rule(file_path=st.sampled_from(TARGETS + ("elsewhere.py",)))
    def write_code(self, file_path):
        before = self.attempt(self.sm.write_code, file_path)
        if before is not None:
            assert self.sm.phase == "implement"
            assert file_path in self.sm.target_files

    @rule()
    def refactor_code(self):
        before = self.attempt(self.sm.refactor_code, "tidy")
        if before is not None:
            assert self.sm.phase == "refactor"

    @rule()
    def verify(self):
        before = self.attempt(self.sm.verify)
        if before is not None:
            moved = (before["stack"][-1]["phase"], self.sm.phase)
            assert moved in {("verify_red", "implement"), ("verify_green", "refactor")}

    @rule(passed=counts, failed=counts)
    def run_tests(self, passed, failed):
        before = self.attempt(self.sm.record_test_result, passed, failed)
        if before is None:
            return
        old = before["stack"][-1]
        closed_cycle = old["phase"] == "refactor" and failed == 0 and passed > 0
        assert self.sm.cycle_count == old["cycleCount"] + closed_cycle
        if closed_cycle:
            assert self.sm.phase == "red" and not self.sm.test_declared
        # Only the top level is ever touched by a test run.
        assert self.sm.to_dict()["stack"][:-1] == before["stack"][:-1]

    def walk_the_happy_path(self, steps):
        """Take the first `steps` actions of a clean cycle from RED: 7
        closes the cycle, 8 also declares the next test."""
        cycles = self.sm.cycle_count
        happy_path = [
            lambda: self.sm.write_test("test_cycle"),
            lambda: self.sm.record_test_result(passed=0, failed=1),
            self.sm.verify,
            lambda: self.sm.record_test_result(passed=1, failed=0),
            self.sm.verify,
            lambda: self.sm.refactor_code("tidy"),
            lambda: self.sm.record_test_result(passed=1, failed=0),
            lambda: self.sm.write_test("test_next"),
        ]
        for action in happy_path[:steps]:
            action()
        expected_phase = ("red", "verify_red", "implement", "verify_green",
                          "refactor", "refactor", "red", "red")[steps - 1]
        assert self.sm.phase == expected_phase
        assert self.sm.cycle_count == cycles + (steps >= 7)
        assert self.sm.test_declared == (steps != 7)

    # The states where the gates matter (mid-IMPLEMENT for drill_down, a
    # closed cycle with or without a new pending test for completion and
    # return_to_parent) take many specific actions to reach, which random
    # sequences rarely produce. These two rules get there in one step.

    @precondition(lambda self: self.sm.phase == "red")
    @rule(steps=st.integers(min_value=1, max_value=8))
    def drive_the_cycle(self, steps):
        self.walk_the_happy_path(steps)

    @precondition(lambda self: self.sm.phase == "implement")
    @rule(declare_next=st.booleans())
    def drill_into_a_finished_level(self, declare_next):
        self.sm.drill_down("tests/test_nested.py", ["a.py"])
        self.walk_the_happy_path(8 if declare_next else 7)

    # -- invariants --------------------------------------------------------

    @invariant()
    def feature_name_tracks_stack(self):
        assert (self.sm.depth == 0) == (self.sm.feature_name is None)

    @invariant()
    def levels_are_well_formed(self):
        for level in self.sm.stack:
            assert level.phase in PHASES
            assert level.cycle_count >= 0
        if self.sm.stack:
            assert self.sm.stack[0].target_files == ()
        # Drilling down is only possible from IMPLEMENT, and only the top
        # level ever changes phase, so every parent is mid-IMPLEMENT.
        assert all(level.phase == "implement" for level in self.sm.stack[:-1])

    @invariant()
    def checkpoint_never_contradicts_last_result(self):
        result = self.sm.last_result
        if self.sm.phase == "verify_red":
            assert result is not None
            assert not (result.failed == 0 and result.passed > 0)
        if self.sm.phase == "verify_green":
            assert result is not None
            assert result.failed == 0

    @invariant()
    def state_survives_a_json_round_trip(self):
        snapshot = self.sm.to_dict()
        reloaded = TDDStateMachine.from_dict(json.loads(json.dumps(snapshot)))
        assert reloaded.to_dict() == snapshot


TDDWorkflow.TestCase.settings = settings(
    max_examples=600,
    stateful_step_count=50,
    deadline=None,
    database=None,  # never write a .hypothesis/ directory into the repo
    suppress_health_check=[HealthCheck.too_slow],
)
test_tdd_workflow_invariants = TDDWorkflow.TestCase
