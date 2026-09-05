"""Pure phase logic for Outside-In TDD. No I/O, no MCP, no subprocess code.

A feature is a stack of test-target "levels", not a single flat test file.
init_feature() pushes the base level (typically a functional/acceptance
test). drill_down() pushes a nested level for any test target you need
along the way — a unit test, a different Django app's tests, whatever —
each running its own independent
RED->VERIFY_RED->IMPLEMENT->VERIFY_GREEN->REFACTOR cycle.
return_to_parent() pops back once a nested level finishes a full cycle.
There's no "acceptance"/"unit" label anywhere: depth in the stack is the
only signal, since a feature may fan out into any number of test files
across any number of areas of the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


PHASES = ("red", "verify_red", "implement", "verify_green", "refactor")

TOOLS_BY_PHASE = {
    "red": ("write_test", "run_tests", "get_status", "init_feature"),
    "verify_red": ("verify", "get_status"),
    "implement": ("write_code", "run_tests", "get_status"),
    "verify_green": ("verify", "get_status"),
    "refactor": ("refactor_code", "run_tests", "get_status"),
}


class PhaseError(Exception):
    """Raised when a tool is called outside its allowed phase."""


class NoActiveFeatureError(Exception):
    """Raised when a feature-scoped tool is called with no feature initialized."""


@dataclass
class TestResult:
    passed: int = 0
    failed: int = 0
    duration_ms: int = 0
    failures: list = field(default_factory=list)
    raw_output: str = ""


@dataclass
class _Level:
    test_file: str
    phase: str = "red"
    cycle_count: int = 0
    last_result: TestResult | None = None
    last_error: str | None = None


class TDDStateMachine:
    def __init__(self) -> None:
        self.feature_name: str | None = None
        self.stack: list[_Level] = []

    # -- current (top-of-stack) level, exposed as plain attributes -----

    @property
    def test_file(self) -> str | None:
        return self.stack[-1].test_file if self.stack else None

    @property
    def phase(self) -> str | None:
        return self.stack[-1].phase if self.stack else None

    @property
    def cycle_count(self) -> int:
        return self.stack[-1].cycle_count if self.stack else 0

    @property
    def last_result(self) -> TestResult | None:
        return self.stack[-1].last_result if self.stack else None

    @property
    def last_error(self) -> str | None:
        return self.stack[-1].last_error if self.stack else None

    @property
    def depth(self) -> int:
        return len(self.stack)

    # -- lifecycle -----------------------------------------------------

    def init_feature(self, name: str, test_file: str) -> None:
        self.feature_name = name
        self.stack = [_Level(test_file=test_file)]

    def reset_feature(self) -> None:
        self.feature_name = None
        self.stack = []

    def complete_feature(self) -> dict[str, Any]:
        """Mark the current feature done. Requires being back at the base
        level (depth 1 — return_to_parent() out of any drill-downs first)
        with at least one full cycle finished there. Distinct from
        reset_feature(), which discards a feature unconditionally from any
        phase or depth."""
        self._require_feature()
        if len(self.stack) != 1:
            raise PhaseError(
                "complete_feature() is only allowed at the base level "
                f"(currently {len(self.stack)} levels deep — "
                "return_to_parent() first)."
            )
        base = self.stack[0]
        if base.phase != "red":
            raise PhaseError(
                "complete_feature() is only allowed in RED phase after at "
                f"least one full cycle (current phase: {base.phase.upper()})."
            )
        if base.cycle_count < 1:
            raise PhaseError(
                "complete_feature() requires at least one full "
                "RED->VERIFY_RED->IMPLEMENT->VERIFY_GREEN->REFACTOR cycle to complete "
                f"(cycle_count={base.cycle_count})."
            )
        summary = {
            "featureName": self.feature_name,
            "testFile": base.test_file,
            "cyclesCompleted": base.cycle_count,
        }
        self.reset_feature()
        return summary

    # -- drill-down stack ------------------------------------------------

    def drill_down(self, test_file: str) -> None:
        """Push a nested test target on top of the current one. Only
        allowed while IMPLEMENT-ing the level above — you're mid
        implementation and need a lower-level test (a different app, a unit
        test, anything) to get there."""
        self._require_phase("implement", "drill_down")
        self.stack.append(_Level(test_file=test_file))

    def return_to_parent(self) -> dict[str, Any]:
        """Pop the current level and resume the one beneath it. Requires
        the current level to have finished at least one full cycle (back in
        RED, cycle_count >= 1) — same completion gate complete_feature()
        uses, just scoped to one level instead of the whole feature."""
        self._require_feature()
        if len(self.stack) < 2:
            raise PhaseError(
                "return_to_parent() requires an active drill-down "
                "(currently at the base level)."
            )
        top = self.stack[-1]
        if top.phase != "red":
            raise PhaseError(
                "return_to_parent() is only allowed in RED phase after at "
                f"least one full cycle at this level (current phase: "
                f"{top.phase.upper()})."
            )
        if top.cycle_count < 1:
            raise PhaseError(
                "return_to_parent() requires at least one full "
                "RED->VERIFY_RED->IMPLEMENT->VERIFY_GREEN->REFACTOR cycle at this level to "
                f"return (cycle_count={top.cycle_count})."
            )
        summary = {"testFile": top.test_file, "cyclesCompleted": top.cycle_count}
        self.stack.pop()
        return summary

    def abandon_drill_down(self) -> dict[str, Any]:
        """Unconditionally pop the current drill-down level, discarding
        whatever progress was made there, and resume the parent exactly
        where it was. Unlike return_to_parent(), this doesn't require the
        nested level to have finished a cycle — use it when a drilled-down
        test turns out not to be needed after all. For discarding the whole
        feature (depth 1), use reset_feature() instead."""
        self._require_feature()
        if len(self.stack) < 2:
            raise PhaseError(
                "abandon_drill_down() requires an active drill-down "
                "(currently at the base level — use reset_feature() to "
                "discard the whole feature)."
            )
        top = self.stack.pop()
        return {
            "testFile": top.test_file,
            "phase": top.phase,
            "cycleCount": top.cycle_count,
        }

    def _require_feature(self) -> None:
        if not self.stack:
            raise NoActiveFeatureError(
                "No active feature. Call init_feature() first."
            )

    def _require_phase(self, expected: str, tool: str) -> None:
        self._require_feature()
        if self.phase != expected:
            raise PhaseError(
                f"{tool}() is only allowed in {expected.upper()} phase "
                f"(current phase: {self.phase.upper()})."
            )

    # -- gated actions ---------------------------------------------------

    def write_test(self, test_name: str) -> None:
        self._require_phase("red", "write_test")

    def write_test_skeleton(self, test_name: str) -> None:
        """Same RED-only gate as write_test — a distinctly-named tool for
        writing TODO-annotated stubs instead of finished assertions.
        Optional: use it only when the workflow calls for pausing on a
        skeleton (e.g. so a human can fill in test-case TODOs) before a
        later write_test / write_test_skeleton call fills them in. No
        different enforcement from write_test — same phase, same lack of
        content tracking."""
        self._require_phase("red", "write_test_skeleton")

    def write_code(self, file_path: str) -> None:
        self._require_phase("implement", "write_code")

    def refactor_code(self, description: str) -> None:
        self._require_phase("refactor", "refactor_code")

    def verify(self) -> None:
        """User confirms the current checkpoint (a failing test in RED, or
        a passing implementation) before the cycle proceeds. Only allowed
        in VERIFY_RED or VERIFY_GREEN phase."""
        self._require_feature()
        level = self.stack[-1]
        if level.phase == "verify_red":
            level.phase = "implement"
        elif level.phase == "verify_green":
            level.phase = "refactor"
        else:
            raise PhaseError(
                "verify() is only allowed in VERIFY_RED or VERIFY_GREEN "
                f"phase (current phase: {level.phase.upper()})."
            )

    def set_last_error(self, message: str) -> None:
        """Override the current level's last_error — for a caller (server.py)
        that has more context than record_test_result's generic per-phase
        message, e.g. distinguishing "this refactor broke its own test" from
        "an unrelated regression was found elsewhere"."""
        self._require_feature()
        self.stack[-1].last_error = message

    # -- run_tests: the only phase-advancing action -----------------------

    def record_test_result(
        self,
        passed: int,
        failed: int,
        duration_ms: int = 0,
        failures: list | None = None,
        raw_output: str = "",
    ) -> str:
        self._require_feature()
        level = self.stack[-1]
        level.last_result = TestResult(
            passed=passed,
            failed=failed,
            duration_ms=duration_ms,
            failures=failures or [],
            raw_output=raw_output,
        )
        level.last_error = None

        if level.phase == "red":
            if failed > 0:
                level.phase = "verify_red"
            elif passed > 0:
                # Test already passes with no implementation change: skip
                # straight to verifying green.
                level.phase = "verify_green"
            # else: no tests ran at all — stay RED.

        elif level.phase == "implement":
            if failed > 0:
                pass  # stay IMPLEMENT, keep fixing
            elif passed > 0:
                level.phase = "verify_green"

        elif level.phase == "refactor":
            if failed > 0:
                level.last_error = "Refactor broke the tests."
                # stay REFACTOR
            else:
                level.phase = "red"
                level.cycle_count += 1

        return self.phase

    # -- introspection ---------------------------------------------------

    def available_tools(self) -> tuple:
        if self.phase is None:
            return ("init_feature", "get_status")
        return TOOLS_BY_PHASE[self.phase]

    def status(
        self, *, include_stack: bool = False, include_last_result: bool = True
    ) -> dict[str, Any]:
        """Build the status payload attached to tool responses.

        Both extras default off/minimal for most calls to keep per-response
        size down — only get_status() (include_stack) and calls that can
        actually change last_result (include_last_result) need the full
        picture; the caller decides per tool in server.py.
        """
        payload: dict[str, Any] = {
            "featureName": self.feature_name,
            "depth": self.depth,
            "testFile": self.test_file,
            "phase": self.phase,
            "cycleCount": self.cycle_count,
            "lastError": self.last_error,
        }
        if include_stack:
            payload["stack"] = [
                {
                    "testFile": lvl.test_file,
                    "phase": lvl.phase,
                    "cycleCount": lvl.cycle_count,
                }
                for lvl in self.stack
            ]
        if include_last_result:
            payload["lastResult"] = (
                None
                if self.last_result is None
                else {
                    "passed": self.last_result.passed,
                    "failed": self.last_result.failed,
                    "durationMs": self.last_result.duration_ms,
                    "failures": self.last_result.failures,
                }
            )
        return payload
