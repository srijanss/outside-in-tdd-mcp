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

Each level declares the implementation file(s) it owns (target_files, set
by drill_down() -- init_feature() always starts the base level with an
empty target_files, since it never owns implementation files directly).
write_code() may only target one of the
current level's declared files — writing to anything else, new file or
existing one, means that content needs its own test first: drill_down()
into it instead of implementing it directly. This is what keeps IMPLEMENT
from becoming "write the whole feature in one shot" — a leaf level's own
RED test justifies its own write_code() calls, but a parent level can never
bypass drilling down just because it's convenient to write more there.
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


class InvalidTargetFilesError(Exception):
    """Raised when target_files isn't a list/tuple of strings."""


def _validate_target_files(target_files: Any) -> tuple[str, ...]:
    if isinstance(target_files, str) or not isinstance(target_files, (list, tuple)):
        raise InvalidTargetFilesError(
            "target_files must be a list or tuple of strings, got "
            f"{type(target_files).__name__}."
        )
    if not all(isinstance(t, str) for t in target_files):
        raise InvalidTargetFilesError(
            "target_files must be a list of strings — got non-string "
            f"entries: {target_files!r}."
        )
    if not all(t.strip() for t in target_files):
        raise InvalidTargetFilesError(
            "target_files entries must not be empty or whitespace-only — "
            f"got: {target_files!r}."
        )
    if len(set(target_files)) != len(target_files):
        raise InvalidTargetFilesError(
            f"target_files must not contain duplicate entries — got: {target_files!r}."
        )
    return tuple(target_files)


# Substrings that show up in a test-runner failure message when the test
# fails purely because a name doesn't exist yet (missing class/function/
# module) rather than because its behavior is wrong. These are cheap,
# language-agnostic signatures — no AST/source parsing — used to tell a
# "create this" failure from a "fix this logic" failure so write_code can be
# nudged toward a stub instead of a full implementation.
_MISSING_SYMBOL_SIGNATURES = (
    "modulenotfounderror",
    "importerror",
    "cannot import name",
    "is not defined",
    "has no attribute",
    "cannot find module",
    "has no exported member",
    "is not a constructor",
    "is not a function",
)


def _looks_like_missing_symbol(failures: list) -> bool:
    """True if every failure's message matches a missing-symbol signature
    (see _MISSING_SYMBOL_SIGNATURES) rather than a behavioral assertion
    failure. Empty failures list is not a match."""
    if not failures:
        return False
    for entry in failures:
        message = entry.get("message", "") if isinstance(entry, dict) else ""
        if not isinstance(message, str):
            return False
        lowered = message.lower()
        if not any(sig in lowered for sig in _MISSING_SYMBOL_SIGNATURES):
            return False
        # A test driving a mock/patch usually asserts on the calls made
        # (not just that a name exists), so a bare stub could never pass it.
        if "mock" in lowered:
            return False
    return True


_STUB_ONLY_HINT = (
    "This failure looks like a missing name (import/attribute/reference "
    "error), not a behavioral assertion — write only a minimal stub to "
    "satisfy it (e.g. an empty class, or a method that raises "
    "NotImplementedError / returns a hardcoded value), not its real logic. "
    "Real behavior should be driven by its own failing test in a later "
    "cycle."
)


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
    target_files: tuple[str, ...] = ()
    phase: str = "red"
    cycle_count: int = 0
    last_result: TestResult | None = None
    last_error: str | None = None
    test_declared: bool = False  # write_test seen this cycle


class TDDStateMachine:
    def __init__(self) -> None:
        self.feature_name: str | None = None
        self.stack: list[_Level] = []
        self.review_finding: dict[str, Any] | None = None

    # -- current (top-of-stack) level, exposed as plain attributes -----

    @property
    def test_file(self) -> str | None:
        return self.stack[-1].test_file if self.stack else None

    @property
    def target_files(self) -> tuple[str, ...]:
        return self.stack[-1].target_files if self.stack else ()

    @property
    def phase(self) -> str | None:
        return self.stack[-1].phase if self.stack else None

    @property
    def cycle_count(self) -> int:
        return self.stack[-1].cycle_count if self.stack else 0

    @property
    def test_declared(self) -> bool:
        return self.stack[-1].test_declared if self.stack else False

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

    def init_feature(
        self,
        name: str,
        test_file: str,
        target_files: list[str],
        review_finding: dict[str, Any] | None = None,
    ) -> None:
        if self.stack:
            raise PhaseError(
                f"A feature ('{self.feature_name}') is already active — "
                "call complete_feature() or reset_feature() before "
                "starting a new one."
            )
        validated = _validate_target_files(target_files)
        if validated:
            raise InvalidTargetFilesError(
                "init_feature's target_files must be empty ([]) — the base "
                "level never owns implementation files directly, whether "
                "it's an acceptance test, a refactor-only feature, or "
                "anything else. Declare real target files via drill_down() "
                f"once identified, e.g. drill_down(testFile=..., "
                f"targetFiles={list(validated)!r})."
            )
        self.feature_name = name
        self.stack = [_Level(test_file=test_file, target_files=validated)]
        self.review_finding = review_finding

    def reset_feature(self) -> None:
        self.feature_name = None
        self.stack = []
        self.review_finding = None

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
            "reviewFinding": self.review_finding,
        }
        self.reset_feature()
        return summary

    # -- drill-down stack ------------------------------------------------

    def drill_down(self, test_file: str, target_files: list[str]) -> None:
        """Push a nested test target on top of the current one. Only
        allowed while IMPLEMENT-ing the level above — you're mid
        implementation and need a lower-level test (a different app, a unit
        test, anything) to get there. target_files declares the
        implementation file(s) this nested cycle owns — same rule as
        init_feature's target_files, scoped to this level."""
        self._require_phase("implement", "drill_down")
        validated = _validate_target_files(target_files)
        self.stack.append(_Level(test_file=test_file, target_files=validated))

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
        self.stack[-1].test_declared = True

    def write_test_skeleton(self, test_name: str) -> None:
        """Same RED-only gate as write_test — a distinctly-named tool for
        writing TODO-annotated stubs instead of finished assertions.
        Optional: use it only when the workflow calls for pausing on a
        skeleton (e.g. so a human can fill in test-case TODOs) before a
        later write_test / write_test_skeleton call fills them in. No
        different enforcement from write_test — same phase, same lack of
        content tracking."""
        self._require_phase("red", "write_test_skeleton")
        self.stack[-1].test_declared = True

    def write_code(self, file_path: str) -> None:
        self._require_phase("implement", "write_code")
        level = self.stack[-1]
        # Exact string match on purpose -- no path normalization ("./f.py"
        # vs "f.py"). Callers must declare target_files in the same form
        # they'll pass to write_code().
        if file_path not in level.target_files:
            raise PhaseError(
                f"write_code() target '{file_path}' is not one of this "
                f"level's declared target files ({', '.join(str(t) for t in level.target_files) or 'none'}). "
                "If it needs its own test, drill_down(testFile=..., "
                f"targetFiles=[{file_path!r}]) first instead of implementing "
                "it directly."
            )

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
        suppress_stub_hint: bool = False,
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
                if not suppress_stub_hint and _looks_like_missing_symbol(
                    level.last_result.failures
                ):
                    level.last_error = _STUB_ONLY_HINT
            elif passed > 0:
                # Test already passes with no implementation change: skip
                # straight to verifying green.
                level.phase = "verify_green"
            # else: no tests ran at all — stay RED.

        elif level.phase == "implement":
            if failed > 0:
                if not suppress_stub_hint and _looks_like_missing_symbol(
                    level.last_result.failures
                ):
                    level.last_error = _STUB_ONLY_HINT
                # else: stay IMPLEMENT, keep fixing (real assertion failure)
            elif passed > 0:
                level.phase = "verify_green"

        elif level.phase == "refactor":
            if failed > 0:
                level.last_error = "Refactor broke the tests."
                # stay REFACTOR
            elif passed > 0:
                level.phase = "red"
                level.cycle_count += 1
                level.test_declared = False
            else:
                level.last_error = (
                    "No tests ran during the refactor check — the cycle "
                    "isn't closed. Fix the test target and rerun."
                )
                # stay REFACTOR

        return self.phase

    # -- introspection ---------------------------------------------------

    # -- persistence -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Full snapshot of feature_name + the entire stack, suitable for
        writing to disk and reloading via from_dict() -- e.g. so a mid-cycle
        feature survives a server restart or a handoff between separate MCP
        server processes on the same project. Distinct from status(): this
        keeps every field needed to reconstruct exact state (per-level
        last_result/last_error, raw_output included) rather than the
        trimmed response payload."""
        return {
            "featureName": self.feature_name,
            "stack": [
                {
                    "testFile": lvl.test_file,
                    "targetFiles": list(lvl.target_files),
                    "phase": lvl.phase,
                    "cycleCount": lvl.cycle_count,
                    "testDeclared": lvl.test_declared,
                    "lastError": lvl.last_error,
                    "lastResult": (
                        None
                        if lvl.last_result is None
                        else {
                            "passed": lvl.last_result.passed,
                            "failed": lvl.last_result.failed,
                            "durationMs": lvl.last_result.duration_ms,
                            "failures": lvl.last_result.failures,
                            "rawOutput": lvl.last_result.raw_output,
                        }
                    ),
                }
                for lvl in self.stack
            ],
            "reviewFinding": self.review_finding,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "TDDStateMachine":
        """Reconstruct a TDDStateMachine from to_dict() output. Best-effort,
        matching this project's convention for on-disk state (see
        TDDServer._load_features): any malformed/unexpected shape falls back
        to a fresh, empty state machine rather than raising, since a corrupt
        state file should never block starting a new feature. A malformed
        entry partway through the stack (e.g. a half-written top-of-stack
        level) only drops that level and anything above it -- the valid
        levels below it are still trustworthy and are kept rather than
        discarding the whole in-progress feature."""
        sm = cls()
        if not isinstance(data, dict):
            return sm
        feature_name = data.get("featureName")
        stack_data = data.get("stack")
        if not isinstance(feature_name, str) or not isinstance(stack_data, list) or not stack_data:
            return sm
        levels: list[_Level] = []
        for entry in stack_data:
            if not isinstance(entry, dict):
                break
            test_file = entry.get("testFile")
            phase = entry.get("phase")
            if not isinstance(test_file, str) or phase not in PHASES:
                break
            try:
                target_files = _validate_target_files(entry.get("targetFiles") or [])
            except InvalidTargetFilesError:
                break
            cycle_count = entry.get("cycleCount", 0)
            if not isinstance(cycle_count, int):
                cycle_count = 0
            last_error = entry.get("lastError")
            if not isinstance(last_error, str):
                last_error = None
            result_data = entry.get("lastResult")
            last_result = None
            if isinstance(result_data, dict):
                failures = result_data.get("failures")
                last_result = TestResult(
                    passed=result_data.get("passed", 0)
                    if isinstance(result_data.get("passed"), int)
                    else 0,
                    failed=result_data.get("failed", 0)
                    if isinstance(result_data.get("failed"), int)
                    else 0,
                    duration_ms=result_data.get("durationMs", 0)
                    if isinstance(result_data.get("durationMs"), int)
                    else 0,
                    failures=failures if isinstance(failures, list) else [],
                    raw_output=result_data.get("rawOutput", "")
                    if isinstance(result_data.get("rawOutput"), str)
                    else "",
                )
            levels.append(
                _Level(
                    test_file=test_file,
                    target_files=target_files,
                    phase=phase,
                    cycle_count=cycle_count,
                    last_result=last_result,
                    last_error=last_error,
                    test_declared=entry.get("testDeclared") is True,
                )
            )
        if not levels:
            return cls()
        sm.feature_name = feature_name
        sm.stack = levels
        review_finding = data.get("reviewFinding")
        if (
            isinstance(review_finding, dict)
            and isinstance(review_finding.get("id"), str)
            and isinstance(review_finding.get("scope"), str)
        ):
            sm.review_finding = review_finding
        return sm

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
            "targetFiles": list(self.target_files),
            "phase": self.phase,
            "cycleCount": self.cycle_count,
            "lastError": self.last_error,
        }
        if include_stack:
            payload["stack"] = [
                {
                    "testFile": lvl.test_file,
                    "targetFiles": list(lvl.target_files),
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
