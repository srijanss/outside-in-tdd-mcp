"""Pure phase logic for Outside-In TDD. No I/O, no MCP, no subprocess code."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


PHASES = ("red", "implement", "green", "refactor")

TOOLS_BY_PHASE = {
    "red": ("write_test", "run_tests", "get_status", "init_feature"),
    "implement": ("write_code", "run_tests", "get_status"),
    "green": ("run_tests", "get_status"),
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


class TDDStateMachine:
    def __init__(self) -> None:
        self.feature_name: str | None = None
        self.test_file: str | None = None
        self.phase: str | None = None
        self.cycle_count: int = 0
        self.last_result: TestResult | None = None
        self.last_error: str | None = None

    # -- lifecycle -----------------------------------------------------

    def init_feature(self, name: str, test_file: str) -> None:
        self.feature_name = name
        self.test_file = test_file
        self.phase = "red"
        self.cycle_count = 0
        self.last_result = None
        self.last_error = None

    def reset_feature(self) -> None:
        self.feature_name = None
        self.test_file = None
        self.phase = None
        self.cycle_count = 0
        self.last_result = None
        self.last_error = None

    def _require_feature(self) -> None:
        if self.phase is None:
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

    def write_test(self, test_name: str, code: str) -> None:
        self._require_phase("red", "write_test")

    def write_code(self, file_path: str, code: str) -> None:
        self._require_phase("implement", "write_code")

    def refactor_code(self, description: str) -> None:
        self._require_phase("refactor", "refactor_code")

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
        self.last_result = TestResult(
            passed=passed,
            failed=failed,
            duration_ms=duration_ms,
            failures=failures or [],
            raw_output=raw_output,
        )
        self.last_error = None

        if self.phase == "red":
            if failed > 0:
                self.phase = "implement"
            elif passed > 0:
                # Test already passes with no implementation change: skip
                # straight to GREEN.
                self.phase = "green"
            # else: no tests ran at all — stay RED.

        elif self.phase == "implement":
            if failed > 0:
                pass  # stay IMPLEMENT, keep fixing
            elif passed > 0:
                self.phase = "green"

        elif self.phase == "green":
            self.phase = "refactor"

        elif self.phase == "refactor":
            if failed > 0:
                self.last_error = "Refactor broke the tests."
                # stay REFACTOR
            else:
                self.phase = "red"
                self.cycle_count += 1

        return self.phase

    # -- introspection ---------------------------------------------------

    def available_tools(self) -> tuple:
        if self.phase is None:
            return ("init_feature", "get_status")
        return TOOLS_BY_PHASE[self.phase]

    def status(self) -> dict[str, Any]:
        return {
            "featureName": self.feature_name,
            "testFile": self.test_file,
            "phase": self.phase,
            "cycleCount": self.cycle_count,
            "lastResult": None
            if self.last_result is None
            else {
                "passed": self.last_result.passed,
                "failed": self.last_result.failed,
                "durationMs": self.last_result.duration_ms,
                "failures": self.last_result.failures,
            },
            "lastError": self.last_error,
            "availableTools": list(self.available_tools()),
        }
