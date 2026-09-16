"""MCP protocol handler (stdio transport). Glue between the MCP tool calls,
the phase state machine, and the configured test-runner adapter.

No language- or framework-specific logic belongs here — see adapter_contract.py
and adapters/*/run.sh for that.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - POSIX-only; best-effort elsewhere too
    fcntl = None

import mcp.server.stdio
from mcp import types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from core.adapter_contract import AdapterError, run_adapter
from core.review_findings import list_review_findings as _list_review_findings
from core.review_findings import record_review_finding as _record_review_finding
from core.research_log import list_research as _list_research_entries
from core.research_log import record_research as _record_research_entry
from core.state_machine import (
    InvalidTargetFilesError,
    NoActiveFeatureError,
    PhaseError,
    TDDStateMachine,
)

PROJECT_ROOT = os.environ.get("TDD_PROJECT_ROOT", "/app")
CONFIG_PATH = os.environ.get(
    "TDD_CONFIG_PATH", str(Path(PROJECT_ROOT) / ".tdd-config.json")
)

TOOLS = [
    types.Tool(
        name="init_feature",
        description=(
            "Start a new TDD feature. Sets phase to RED. If featureName "
            "matches an entry in .tdd-features.json (an upfront plan "
            "breakdown), checks that entry's dependsOn are all "
            "'completed' first (rejecting with an error listing any "
            "unmet dependencies) and flips its status to 'in_progress'. "
            "featureName not in the plan starts normally, ad hoc."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "featureName": {"type": "string"},
                "testFile": {
                    "type": "string",
                    "description": (
                        "Test target(s), relative to project root (passed "
                        "as-is to the adapter, e.g. a pytest path expression)."
                    ),
                },
                "targetFiles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Must be an empty list ([]) — the base level never "
                        "owns implementation files directly, regardless of "
                        "whether testFile is an acceptance test, a unit "
                        "test, or a refactor-only feature. Passing any "
                        "entries here is rejected. Declare real "
                        "implementation file(s) via drill_down(testFile, "
                        "targetFiles) once identified — write_code() only "
                        "works inside a drilled-down level's declared "
                        "target files."
                    ),
                },
                "reviewFindingId": {
                    "type": "string",
                    "description": (
                        "Set when this feature is the fix for a persisted "
                        "review finding (see record_review_finding) — its "
                        "'id'. Requires reviewFindingScope too. On "
                        "complete_feature, that finding is automatically "
                        "re-recorded with status 'fixed'."
                    ),
                },
                "reviewFindingScope": {
                    "type": "string",
                    "description": (
                        "The scope the reviewFindingId was recorded under."
                    ),
                },
            },
            "required": ["featureName", "testFile", "targetFiles"],
        },
    ),
    types.Tool(
        name="write_test",
        description=(
            "Declare a failing test written to disk (via your own file "
            "tools). Only available in RED phase."
        ),
        inputSchema={
            "type": "object",
            "properties": {"testName": {"type": "string"}},
            "required": ["testName"],
        },
    ),
    types.Tool(
        name="write_test_skeleton",
        description=(
            "Declare a TODO-annotated test stub written to disk instead of "
            "a finished test. RED phase only. Use only if the "
            "skeleton-first workflow was explicitly requested — otherwise "
            "use write_test."
        ),
        inputSchema={
            "type": "object",
            "properties": {"testName": {"type": "string"}},
            "required": ["testName"],
        },
    ),
    types.Tool(
        name="write_code",
        description=(
            "Declare implementation code written to disk (via your own "
            "file tools). Only available in IMPLEMENT phase, and only for "
            "one of the current level's declared targetFiles (see "
            "init_feature/drill_down) — new file or existing one. If the "
            "content you need belongs in a different file, drill_down into "
            "it with a test first instead of writing it here directly.\n\n"
            "Minimal-diff rule: before calling this, check every line "
            "you're about to write against the CURRENTLY FAILING test "
            "only. If a line isn't needed to turn that one test green, "
            "delete it — even if you can see it will obviously be needed "
            "later. If the failing test creates or references a NEW "
            "collaborator class/object only to check it exists, gets "
            "called, or gets passed around (its own logic isn't asserted "
            "on), implement that collaborator as a stub only (hardcoded "
            "return / NotImplementedError) — its real logic gets its own "
            "drill_down with its own failing test later. Gut-check: if "
            "removing a chunk of what you wrote wouldn't make the current "
            "failing test fail again, don't write that chunk yet."
        ),
        inputSchema={
            "type": "object",
            "properties": {"filePath": {"type": "string"}},
            "required": ["filePath"],
        },
    ),
    types.Tool(
        name="verify",
        description=(
            "User confirms the checkpoint (failing test or passing impl) "
            "and advances the cycle. VERIFY_RED or VERIFY_GREEN phase only."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="run_tests",
        description=(
            "Run the test suite via the configured adapter. "
            "Auto-advances phase based on results. Closing a base-level "
            "REFACTOR with defaultTestDir configured returns "
            "needsRegressionScopeConfirmation instead of running the full "
            "sweep — re-call with regressionScope set to a path/expression "
            "(or \"skip\") to proceed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "regressionScope": {
                    "type": "string",
                    "description": (
                        "Scope for the closing-REFACTOR regression sweep: a "
                        "path/pytest expression to use instead of "
                        "defaultTestDir, or \"skip\" to skip it entirely."
                    ),
                }
            },
        },
    ),
    types.Tool(
        name="refactor_code",
        description=(
            "Declare a refactor made on disk (via your own file tools), "
            "tests still green. Only available in REFACTOR phase."
        ),
        inputSchema={
            "type": "object",
            "properties": {"description": {"type": "string"}},
            "required": ["description"],
        },
    ),
    types.Tool(
        name="get_status",
        description="Get current feature, phase, drill-down stack, and last test result.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="list_features",
        description=(
            "List the feature ledger (.tdd-features.json) — an optional "
            "upfront plan (write this file yourself as an array of "
            "{featureName, description, dependsOn: [featureName,...], "
            "status: 'draft'} entries before starting work — a human must "
            "then call approve_plan() to flip 'draft' entries to "
            "'pending' before init_feature will accept them) that "
            "init_feature/complete_feature/reset_feature update in place "
            "as work progresses (status becomes 'in_progress', "
            "'completed', or 'abandoned'; testFile/targetFiles/"
            "cyclesCompleted get filled in). Features started without a "
            "matching plan entry are appended automatically. Use this to "
            "see what's done, in progress, or blocked on dependencies — "
            "especially when resuming after a cleared/summarized session."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="remove_completed_features",
        description=(
            "Remove all completed entries from .tdd-features.json. Also "
            "removes those names from dependsOn on retained entries so "
            "pruning does not block pending features. Does not affect the "
            "active TDD state."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="approve_plan",
        description=(
            "Human-only checkpoint (no auto-approval, mirroring verify()) "
            "that flips 'draft' entries in the feature ledger "
            "(.tdd-features.json) to 'pending', clearing them to be "
            "started via init_feature. With no arguments, approves every "
            "'draft' entry; pass featureNames to approve only those."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "featureNames": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Only approve these entries (must currently be "
                        "'draft'). Omit to approve every 'draft' entry in "
                        "the ledger."
                    ),
                },
            },
        },
    ),
    types.Tool(
        name="reset_feature",
        description=(
            "Discard the current feature from any phase and clear state. "
            "Use complete_feature instead if it's actually done."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="complete_feature",
        description=(
            "Mark the current feature complete and clear its state. Only "
            "at base level (depth 1) in RED phase, after >=1 full cycle."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="drill_down",
        description=(
            "Push a nested test target on top of the current one — required "
            "whenever IMPLEMENT needs to write to a file that isn't one of "
            "the current level's declared targetFiles (e.g. a new module or "
            "collaborator), new or existing. IMPLEMENT phase only; runs its "
            "own RED->...->REFACTOR cycle scoped to targetFiles declared "
            "here. Call return_to_parent when done."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "testFile": {"type": "string"},
                "targetFiles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Implementation file(s) this nested level owns — "
                        "same rule as init_feature's targetFiles."
                    ),
                },
            },
            "required": ["testFile", "targetFiles"],
        },
    ),
    types.Tool(
        name="return_to_parent",
        description=(
            "Pop the finished drill-down level and resume the parent. "
            "RED phase only, after >=1 full cycle at this level. Use "
            "abandon_drill_down instead if the level isn't finished."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="abandon_drill_down",
        description=(
            "Unconditionally pop the current drill-down level (no phase/"
            "cycle requirement) when it turns out unneeded. Not allowed "
            "at depth 1 — use reset_feature for that."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="record_review_finding",
        description=(
            "Persist a review finding under a shared feature or diff "
            "scope. A finding recorded with status 'fixed' is removed "
            "from the store rather than kept — the store only ever holds "
            "live (unaddressed) findings."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "scope": {"type": "string"},
                "finding": {"type": "object"},
            },
            "required": ["scope", "finding"],
        },
    ),
    types.Tool(
        name="list_review_findings",
        description="List persisted review findings for a feature or diff scope.",
        inputSchema={
            "type": "object",
            "properties": {"scope": {"type": "string"}},
            "required": ["scope"],
        },
    ),
    types.Tool(
        name="record_research",
        description=(
            "Append an entry to the durable research log "
            "(.tdd-research.json) — external context (a link read, a "
            "design decision, a summary) worth keeping across a /clear or "
            "a fresh session, so it doesn't have to be re-fetched or "
            "re-derived. Not phase-gated; callable any time."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "URL or short description of where this came from.",
                },
                "summary": {
                    "type": "string",
                    "description": "Short summary or bullet points — not the full content.",
                },
                "relatedFeature": {
                    "type": "string",
                    "description": "Optional featureName this research informed.",
                },
            },
            "required": ["source", "summary"],
        },
    ),
    types.Tool(
        name="list_research",
        description=(
            "List the durable research log (.tdd-research.json). Use this "
            "at the start of a session (or after a /clear) instead of "
            "re-fetching a source already recorded via record_research."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="session_start",
        description=(
            "Read-only orientation bundle for a fresh session or after a "
            "/clear: the feature ledger (list_features), current phase/"
            "drill-down stack (get_status), a tail of .tdd-session.log, "
            "and a tail of the durable research log (.tdd-research.json). "
            "Call this first instead of re-deriving context from scratch."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
]


# Caps on what a run_tests() response (and the last_result it gets stored
# as, which get_status() keeps re-sending until the next run_tests()) can
# carry — defensive against an adapter that doesn't cap its own output, and
# against a large regression check surfacing dozens of failures at once.
MAX_FAILURES_RETURNED = 20
MAX_FAILURE_MESSAGE_CHARS = 500


def _cap_failures(failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    capped = [
        {**f, "message": str(f.get("message", ""))[-MAX_FAILURE_MESSAGE_CHARS:]}
        for f in failures[:MAX_FAILURES_RETURNED]
    ]
    omitted = len(failures) - len(capped)
    if omitted > 0:
        capped.append(
            {
                "name": "...",
                "message": f"{omitted} more failure(s) omitted — rerun a "
                "narrower test_target to see them.",
            }
        )
    return capped


class ConfigError(Exception):
    """Raised when .tdd-config.json is missing, malformed, or incomplete."""


def load_config(config_path: str) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f".tdd-config.json not found at '{config_path}'. "
            "Create one with 'adapter', 'adapterPath', 'defaultTestDir'."
        )
    with path.open() as f:
        try:
            config = json.load(f)
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"'{config_path}' is not valid JSON: {exc}"
            ) from exc

    if not isinstance(config, dict):
        raise ConfigError(
            f"'{config_path}' must contain a JSON object, got {type(config).__name__}."
        )

    _require_string(config, "adapterPath", config_path, required=True)
    _require_string(config, "defaultTestDir", config_path, required=False)

    return config


def _require_string(
    config: dict[str, Any], field: str, config_path: str, *, required: bool
) -> None:
    if field not in config:
        if required:
            raise ConfigError(
                f"'{config_path}' is missing required field '{field}'."
            )
        return
    if not isinstance(config[field], str) or (required and not config[field]):
        raise ConfigError(
            f"'{config_path}' field '{field}' must be a non-empty string."
            if required
            else f"'{config_path}' field '{field}' must be a string."
        )


class TDDServer:
    def __init__(
        self, project_root: str, config_path: str, state_path: str | None = None
    ) -> None:
        self.project_root = project_root
        self.config_path = config_path
        self.sm = TDDStateMachine()
        self.session_log_path = os.environ.get(
            "TDD_SESSION_LOG_PATH", str(Path(project_root) / ".tdd-session.log")
        )
        self.features_path = os.environ.get(
            "TDD_FEATURES_PATH", str(Path(project_root) / ".tdd-features.json")
        )
        self.research_path = os.environ.get(
            "TDD_RESEARCH_PATH", str(Path(project_root) / ".tdd-research.json")
        )
        self.review_findings_path = str(
            Path(project_root) / ".tdd-review-findings.json"
        )
        # Unlike the paths above, this one is also accepted as a
        # constructor argument (not just an env var / post-construction
        # attribute override): it's loaded eagerly right below, before a
        # caller gets a chance to reassign the attribute, so a test that
        # only overrides it after construction (as with features_path)
        # would still load real leftover state from project_root first.
        self.state_path = state_path or os.environ.get(
            "TDD_STATE_PATH", str(Path(project_root) / ".tdd-state.json")
        )
        self._load_state()

    def _load_state(self) -> None:
        path = Path(self.state_path)
        if not path.exists():
            return
        try:
            with self._state_lock(), path.open() as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        self.sm = TDDStateMachine.from_dict(data)

    def _save_state(self) -> None:
        # Same write-to-temp-then-rename pattern as _save_features, so a
        # crash mid-write never leaves .tdd-state.json truncated/partial.
        # Serialization and the write are guarded separately (matching
        # _log_event): a non-serializable field (TypeError) must never
        # block the TDD cycle any more than an unwritable path (OSError)
        # does.
        try:
            content = json.dumps(self.sm.to_dict(), indent=2) + "\n"
        except TypeError:
            return
        tmp_path = f"{self.state_path}.tmp"
        try:
            with self._state_lock():
                with open(tmp_path, "w") as f:
                    f.write(content)
                os.replace(tmp_path, self.state_path)
        except OSError:
            pass  # persisted cycle state is best-effort; never block the TDD cycle

    def _load_features(self) -> list[dict[str, Any]]:
        path = Path(self.features_path)
        if not path.exists():
            return []
        try:
            with path.open() as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def _save_features(self, features: list[dict[str, Any]]) -> None:
        # Write to a temp file and rename into place (atomic on POSIX and
        # Windows for a same-filesystem replace) so a crash mid-write never
        # leaves .tdd-features.json truncated/partial.
        tmp_path = f"{self.features_path}.tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(features, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, self.features_path)
        except OSError:
            pass  # feature ledger is best-effort; never block the TDD cycle

    @contextlib.contextmanager
    def _file_lock(self, path: str):
        """Exclusive lock around a read-modify-write of the file at `path`,
        so two MCP server processes on the same project (e.g. two
        concurrent Claude Code sessions) can't race and silently drop each
        other's update. Best-effort: if flock isn't available, proceeds
        unlocked rather than blocking the TDD cycle."""
        if fcntl is None:
            yield
            return
        lock_path = f"{path}.lock"
        try:
            lock_file = open(lock_path, "w")
        except OSError:
            yield
            return
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
            finally:
                lock_file.close()

    def _features_lock(self):
        return self._file_lock(self.features_path)

    def _research_lock(self):
        return self._file_lock(self.research_path)

    def _review_findings_lock(self):
        return self._file_lock(self.review_findings_path)

    def _mark_review_finding_fixed(self, review_finding: dict[str, Any]) -> None:
        with self._review_findings_lock():
            existing = {
                finding["id"]: finding
                for finding in _list_review_findings(
                    review_finding["scope"], path=self.review_findings_path
                )
            }
            fixed = {
                **existing.get(review_finding["id"], {}),
                "id": review_finding["id"],
                "status": "fixed",
            }
            _record_review_finding(
                review_finding["scope"], fixed, path=self.review_findings_path
            )

    def _state_lock(self):
        return self._file_lock(self.state_path)

    def _find_feature(
        self, features: list[dict[str, Any]], feature_name: str
    ) -> dict[str, Any] | None:
        for entry in features:
            if isinstance(entry, dict) and entry.get("featureName") == feature_name:
                return entry
        return None

    def _features_structure_error(self, features: list[Any]) -> str | None:
        for entry in features:
            if not isinstance(entry, dict):
                return (
                    f"'{self.features_path}' contains a malformed entry "
                    f"(not a JSON object): {entry!r}. Fix the ledger before "
                    "starting a feature."
                )
            name = entry.get("featureName")
            if not isinstance(name, str) or not name.strip():
                return (
                    f"'{self.features_path}' contains an entry with a "
                    f"missing or invalid featureName: {entry!r}."
                )
            if "dependsOn" in entry:
                depends_on = entry["dependsOn"]
                if not isinstance(depends_on, list) or not all(
                    isinstance(dep, str) for dep in depends_on
                ):
                    return (
                        f"'{self.features_path}' entry '{name}' has an "
                        f"invalid dependsOn (must be a list of strings): "
                        f"{depends_on!r}."
                    )
        return None

    def _has_dependency_cycle(
        self, features: list[dict[str, Any]], feature_name: str
    ) -> bool:
        """True if feature_name's dependsOn chain (transitively) loops back
        on itself — including a feature naming itself directly."""

        def visit(name: str, ancestors: frozenset[str]) -> bool:
            if name in ancestors:
                return True
            entry = self._find_feature(features, name)
            if entry is None:
                return False
            return any(
                visit(dep, ancestors | {name})
                for dep in entry.get("dependsOn") or []
                if isinstance(dep, str)
            )

        entry = self._find_feature(features, feature_name)
        if entry is None:
            return False
        return any(
            visit(dep, frozenset({feature_name}))
            for dep in entry.get("dependsOn") or []
            if isinstance(dep, str)
        )

    def _validate_feature_start(
        self, features: list[dict[str, Any]], feature_name: str
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Checks whether feature_name is startable given the ledger.
        Returns (error, plan_entry): error is None when clear to proceed;
        plan_entry is None for an ad hoc feature not present in the ledger
        (always clear to proceed, no plan/dependency checks apply)."""
        structure_error = self._features_structure_error(features)
        if structure_error:
            return structure_error, None

        plan_entry = self._find_feature(features, feature_name)
        if plan_entry is None:
            return None, None

        status = plan_entry.get("status")
        if status == "draft":
            return (
                f"Feature '{feature_name}' is still 'draft' in "
                ".tdd-features.json. Call approve_plan() to approve it "
                "before starting."
            ), plan_entry
        if status == "completed":
            return (
                f"Feature '{feature_name}' is already marked 'completed' "
                "in .tdd-features.json. Use a different featureName, or "
                "edit the ledger directly if this is intentional rework."
            ), plan_entry
        if status == "in_progress":
            return (
                f"Feature '{feature_name}' is already marked 'in_progress' "
                "in .tdd-features.json."
            ), plan_entry
        if self._has_dependency_cycle(features, feature_name):
            return (
                f"Feature '{feature_name}' has a circular dependency chain "
                "in .tdd-features.json (a dependsOn cycle, possibly "
                "through other features, or naming itself) — fix the plan "
                "before starting."
            ), plan_entry

        depends_on = plan_entry.get("dependsOn") or []
        missing = [
            dep for dep in depends_on if self._find_feature(features, dep) is None
        ]
        incomplete = [
            dep
            for dep in depends_on
            if dep not in missing
            and (self._find_feature(features, dep) or {}).get("status")
            != "completed"
        ]
        if missing or incomplete:
            parts = []
            if missing:
                parts.append(f"not found in the ledger: {', '.join(missing)}")
            if incomplete:
                parts.append(f"not yet completed: {', '.join(incomplete)}")
            return (
                f"Feature '{feature_name}' depends on feature(s) "
                f"{'; '.join(parts)}. Fix the ledger or complete those "
                "first."
            ), plan_entry

        return None, plan_entry

    def _record_feature(
        self,
        *,
        status: str,
        feature_name: str,
        test_file: str | None,
        target_files: list[str] | None = None,
        cycles_completed: int,
    ) -> None:
        """Upsert this feature's entry in the ledger — updates the plan
        entry in place (preserving its dependsOn/description) if one
        already exists from an upfront plan, otherwise appends a new one
        for a feature started ad hoc."""
        with self._features_lock():
            features = self._load_features()
            entry = self._find_feature(features, feature_name)
            if entry is None:
                entry = {"featureName": feature_name, "dependsOn": []}
                features.append(entry)
            entry["testFile"] = test_file
            entry["targetFiles"] = target_files or []
            entry["cyclesCompleted"] = cycles_completed
            entry["status"] = status
            entry["recordedAt"] = datetime.now(timezone.utc).isoformat()
            self._save_features(features)

    def _log_event(self, event: str, **fields: Any) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "featureName": self.sm.feature_name,
            "depth": self.sm.depth,
            "testFile": self.sm.test_file,
            "phase": self.sm.phase,
            **fields,
        }
        try:
            line = json.dumps(entry) + "\n"
        except TypeError:
            return  # a non-serializable field must never block the TDD cycle
        try:
            with open(self.session_log_path, "a") as f:
                f.write(line)
        except OSError:
            pass  # session logging is best-effort; never block the TDD cycle

    def _tail_session_log(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            with open(self.session_log_path) as f:
                lines = f.readlines()
        except OSError:
            return []
        entries: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue  # a corrupted line must never block orientation
            if isinstance(parsed, dict):
                entries.append(parsed)
        return entries

    def _text(self, payload: dict[str, Any]) -> list[types.TextContent]:
        return [
            types.TextContent(
                type="text", text=json.dumps(payload, separators=(",", ":"))
            )
        ]

    def _error(self, message: str) -> list[types.TextContent]:
        return self._text({"error": message})

    def _try_load_config(self) -> tuple[dict[str, Any] | None, str | None]:
        try:
            config = load_config(self.config_path)
        except (FileNotFoundError, ConfigError) as exc:
            return None, str(exc)

        adapter_path = config["adapterPath"]
        if not os.path.dirname(adapter_path):
            # A bare name (no path separator at all) — a PATH-resolvable
            # command, e.g. a console script installed by `pip install`.
            # Left unresolved (falls through unchanged) if not found on
            # PATH, so the existing "does not exist" error still fires.
            resolved = shutil.which(adapter_path)
            if resolved:
                config = {**config, "adapterPath": resolved}
        elif not Path(adapter_path).is_absolute():
            config = {
                **config,
                "adapterPath": str(Path(self.project_root) / adapter_path),
            }
        return config, None

    def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> list[types.TextContent]:
        try:
            return self._call_tool(name, arguments)
        finally:
            self._save_state()

    def _call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> list[types.TextContent]:
        try:
            if name == "init_feature":
                config, error = self._try_load_config()
                if error:
                    return self._error(error)
                adapter_path = config["adapterPath"]
                if not Path(adapter_path).exists():
                    return self._error(
                        f"Configured adapterPath '{adapter_path}' does not "
                        "exist. Fix .tdd-config.json before starting a "
                        "feature."
                    )

                feature_name = arguments["featureName"]
                with self._features_lock():
                    features = self._load_features()
                    plan_error, plan_entry = self._validate_feature_start(
                        features, feature_name
                    )
                    if plan_error:
                        return self._error(plan_error)

                    review_finding_id = arguments.get("reviewFindingId")
                    review_finding_scope = (
                        arguments["reviewFindingScope"]
                        if review_finding_id
                        else None
                    )
                    if review_finding_id:
                        with self._review_findings_lock():
                            findings = _list_review_findings(
                                review_finding_scope,
                                path=self.review_findings_path,
                            )
                        if not any(
                            finding.get("id") == review_finding_id
                            for finding in findings
                        ):
                            return self._error(
                                f"Review finding '{review_finding_id}' does not "
                                f"exist in scope '{review_finding_scope}'."
                            )
                    review_finding = (
                        {
                            "id": review_finding_id,
                            "scope": review_finding_scope,
                        }
                        if review_finding_id
                        else None
                    )
                    self.sm.init_feature(
                        feature_name,
                        arguments["testFile"],
                        arguments["targetFiles"],
                        review_finding=review_finding,
                    )
                    self._log_event(
                        "init_feature", targetFiles=arguments["targetFiles"]
                    )

                    if plan_entry is None:
                        # Ad hoc feature (no matching plan entry) — record it
                        # as in_progress too, not just retroactively at
                        # complete_feature/reset_feature, so list_features()
                        # reflects what's actually running right now.
                        plan_entry = {"featureName": feature_name, "dependsOn": []}
                        features.append(plan_entry)
                    plan_entry["status"] = "in_progress"
                    plan_entry["testFile"] = arguments["testFile"]
                    plan_entry["targetFiles"] = list(arguments["targetFiles"])
                    plan_entry["recordedAt"] = datetime.now(timezone.utc).isoformat()
                    self._save_features(features)

                return self._text(self.sm.status(include_last_result=False))

            if name == "write_test":
                self.sm.write_test(arguments["testName"])
                self._log_event("write_test", testName=arguments["testName"])
                return self._text({"ok": True})

            if name == "write_test_skeleton":
                self.sm.write_test_skeleton(arguments["testName"])
                self._log_event(
                    "write_test_skeleton", testName=arguments["testName"]
                )
                return self._text({"ok": True})

            if name == "write_code":
                self.sm.write_code(arguments["filePath"])
                self._log_event("write_code", filePath=arguments["filePath"])
                return self._text({"ok": True})

            if name == "refactor_code":
                self.sm.refactor_code(arguments["description"])
                self._log_event(
                    "refactor_code", description=arguments["description"]
                )
                return self._text({"ok": True})

            if name == "verify":
                self.sm.verify()
                self._log_event("verify")
                return self._text(
                    {"ok": True, **self.sm.status(include_last_result=False)}
                )

            if name == "run_tests":
                return self._text(
                    self._run_tests(arguments.get("regressionScope"))
                )

            if name == "get_status":
                return self._text(self.sm.status(include_stack=True))

            if name == "list_features":
                return self._text({"features": self._load_features()})

            if name == "remove_completed_features":
                with self._features_lock():
                    features = self._load_features()
                    removed = {
                        entry.get("featureName")
                        for entry in features
                        if isinstance(entry, dict)
                        and entry.get("status") == "completed"
                        and isinstance(entry.get("featureName"), str)
                    }
                    retained = []
                    for entry in features:
                        if not isinstance(entry, dict):
                            retained.append(entry)
                            continue
                        if entry.get("featureName") in removed:
                            continue
                        if isinstance(entry.get("dependsOn"), list):
                            entry["dependsOn"] = [
                                dependency
                                for dependency in entry["dependsOn"]
                                if dependency not in removed
                            ]
                        retained.append(entry)
                    self._save_features(retained)
                self._log_event(
                    "remove_completed_features", removed=sorted(removed)
                )
                return self._text(
                    {
                        "ok": True,
                        "removed": sorted(removed),
                        "remaining": retained,
                    }
                )

            if name == "approve_plan":
                feature_names = arguments.get("featureNames")
                with self._features_lock():
                    features = self._load_features()
                    approved = []
                    for entry in features:
                        if not isinstance(entry, dict):
                            continue
                        name = entry.get("featureName")
                        if not isinstance(name, str) or not name.strip():
                            continue
                        if entry.get("status") != "draft":
                            continue
                        if feature_names is not None and name not in feature_names:
                            continue
                        entry["status"] = "pending"
                        approved.append(name)
                    self._save_features(features)
                self._log_event("approve_plan", approved=approved)
                return self._text({"ok": True, "approved": approved})

            if name == "reset_feature":
                prior_feature = self.sm.feature_name
                prior_test_file = self.sm.test_file
                prior_target_files = list(self.sm.target_files)
                prior_cycle_count = self.sm.cycle_count
                self.sm.reset_feature()
                self._log_event(
                    "reset_feature",
                    featureName=prior_feature,
                    testFile=prior_test_file,
                )
                if prior_feature is not None:
                    self._record_feature(
                        status="abandoned",
                        feature_name=prior_feature,
                        test_file=prior_test_file,
                        target_files=prior_target_files,
                        cycles_completed=prior_cycle_count,
                    )
                return self._text(
                    {"ok": True, **self.sm.status(include_last_result=False)}
                )

            if name == "complete_feature":
                target_files = list(self.sm.target_files)
                summary = self.sm.complete_feature()
                self._log_event(
                    "complete_feature",
                    featureName=summary["featureName"],
                    testFile=summary["testFile"],
                    cyclesCompleted=summary["cyclesCompleted"],
                )
                self._record_feature(
                    status="completed",
                    feature_name=summary["featureName"],
                    test_file=summary["testFile"],
                    target_files=target_files,
                    cycles_completed=summary["cyclesCompleted"],
                )
                if summary.get("reviewFinding"):
                    self._mark_review_finding_fixed(summary["reviewFinding"])
                return self._text(
                    {
                        "ok": True,
                        "message": (
                            f"Feature '{summary['featureName']}' completed "
                            f"after {summary['cyclesCompleted']} cycle(s)."
                        ),
                        **self.sm.status(include_last_result=False),
                    }
                )

            if name == "drill_down":
                self.sm.drill_down(arguments["testFile"], arguments["targetFiles"])
                self._log_event(
                    "drill_down",
                    testFile=arguments["testFile"],
                    targetFiles=arguments["targetFiles"],
                )
                return self._text(
                    {
                        "ok": True,
                        "message": (
                            f"Drilled into '{arguments['testFile']}' "
                            f"(depth {self.sm.depth}). Write a failing test "
                            "there, then call run_tests()."
                        ),
                        **self.sm.status(include_last_result=False),
                    }
                )

            if name == "return_to_parent":
                summary = self.sm.return_to_parent()
                self._log_event(
                    "return_to_parent",
                    testFile=summary["testFile"],
                    cyclesCompleted=summary["cyclesCompleted"],
                )
                return self._text(
                    {
                        "ok": True,
                        "message": (
                            f"Returned from '{summary['testFile']}' after "
                            f"{summary['cyclesCompleted']} cycle(s). "
                            f"Back at depth {self.sm.depth}."
                        ),
                        **self.sm.status(include_last_result=False),
                    }
                )

            if name == "abandon_drill_down":
                summary = self.sm.abandon_drill_down()
                self._log_event(
                    "abandon_drill_down",
                    testFile=summary["testFile"],
                    cyclesCompleted=summary["cycleCount"],
                )
                return self._text(
                    {
                        "ok": True,
                        "message": (
                            f"Abandoned drill-down into '{summary['testFile']}' "
                            f"(was {summary['phase'].upper()}, "
                            f"{summary['cycleCount']} cycle(s) completed). "
                            f"Back at depth {self.sm.depth}."
                        ),
                        **self.sm.status(include_last_result=False),
                    }
                )

            if name == "record_research":
                with self._research_lock():
                    entry = _record_research_entry(
                        source=arguments["source"],
                        summary=arguments["summary"],
                        related_feature=arguments.get("relatedFeature"),
                        path=self.research_path,
                    )
                self._log_event("record_research", source=arguments["source"])
                return self._text({"ok": True, "entry": entry})

            if name == "record_review_finding":
                with self._review_findings_lock():
                    finding = _record_review_finding(
                        arguments["scope"],
                        arguments["finding"],
                        path=self.review_findings_path,
                    )
                return self._text({"ok": True, "finding": finding})

            if name == "list_review_findings":
                with self._review_findings_lock():
                    findings = _list_review_findings(
                        arguments["scope"], path=self.review_findings_path
                    )
                return self._text(
                    {"scope": arguments["scope"], "findings": findings}
                )

            if name == "list_research":
                with self._research_lock():
                    entries = _list_research_entries(path=self.research_path)
                return self._text({"research": entries})

            if name == "session_start":
                with self._research_lock():
                    research = _list_research_entries(path=self.research_path)
                return self._text(
                    {
                        "features": self._load_features(),
                        "status": self.sm.status(include_stack=True),
                        "sessionLog": self._tail_session_log(),
                        "research": research[-20:],
                    }
                )

            return self._error(f"Unknown tool: {name}")

        except (PhaseError, NoActiveFeatureError, InvalidTargetFilesError) as exc:
            return self._error(str(exc))
        except KeyError as exc:
            return self._error(f"Missing required argument: {exc}")

    def _run_tests(self, regression_scope: str | None = None) -> dict[str, Any]:
        if self.sm.phase is None:
            return {"error": "No active feature. Call init_feature() first."}

        config, error = self._try_load_config()
        if error:
            return {"error": error}

        adapter_path = config["adapterPath"]
        test_target = self.sm.test_file
        default_test_dir = config.get("defaultTestDir")
        # A whitespace-only value (e.g. "   ") is truthy but shlex.split()
        # collapses it to nothing — treat it the same as unset rather than
        # running a no-op regression check that looks like real coverage.
        if default_test_dir is not None and not default_test_dir.strip():
            default_test_dir = None

        # Closing a base-level REFACTOR cycle is what unlocks
        # complete_feature() — check the whole suite (not just this cycle's
        # target), so a regression elsewhere can't slip through unnoticed.
        # Nested drill-down levels skip this; only the outer feature's
        # cycle gates completion.
        would_close_base_refactor = (
            self.sm.phase == "refactor" and self.sm.depth == 1 and default_test_dir
        )
        # Running the full defaultTestDir sweep unconditionally can be an
        # unwanted surprise for a large/slow suite — pause and let the
        # caller choose a scope (or "skip") instead of just doing it,
        # before any adapter call happens. Once regression_scope is given,
        # proceed using it in place of defaultTestDir for this call only.
        if would_close_base_refactor and regression_scope is None:
            return {
                "needsRegressionScopeConfirmation": True,
                "suggestedScope": default_test_dir,
                **self.sm.status(),
            }
        if regression_scope == "skip":
            default_test_dir = None
        elif regression_scope is not None:
            default_test_dir = regression_scope

        # test_target and defaultTestDir are run together in one adapter
        # call (rather than two separate calls summed) since defaultTestDir
        # almost always already contains test_target — summing two runs
        # would double-count the overlap, and running it as a single
        # pytest invocation lets pytest's own collection dedupe overlapping
        # paths for free.
        closing_base_refactor = (
            self.sm.phase == "refactor" and self.sm.depth == 1 and default_test_dir
        )
        # defaultTestDir follows the same contract as test_target itself
        # (run.sh's docstring: "a single path, several space-separated
        # paths/dirs, or a full pytest argument expression") — it is not a
        # single opaque path, so it must NOT be shlex.quote()'d as one
        # token. A caller who genuinely needs a literal path containing a
        # space must quote that substring themselves in defaultTestDir
        # (e.g. '"dir with space"'), exactly as run.sh's own shlex.split()
        # already expects.
        if closing_base_refactor:
            try:
                shlex.split(default_test_dir)
            except ValueError as exc:
                return {
                    "error": (
                        f"defaultTestDir in .tdd-config.json is malformed: {exc}"
                    )
                }
        run_target = (
            f"{test_target} {default_test_dir}"
            if closing_base_refactor
            else test_target
        )

        try:
            result = run_adapter(adapter_path, run_target, self.project_root)
        except AdapterError as exc:
            return {"error": f"Adapter failed: {exc}"}

        own_target_broke = None
        has_extra_regressions = False
        if closing_base_refactor and result.failed > 0:
            # Something in the combined run failed — find out whether it's
            # this cycle's own test or a pre-existing regression elsewhere,
            # only now that we actually need to know (rare path).
            try:
                own_result = run_adapter(adapter_path, test_target, self.project_root)
            except AdapterError as exc:
                return {"error": f"Adapter failed: {exc}"}
            own_target_broke = own_result.failed > 0
            has_extra_regressions = result.failed > own_result.failed
            if not own_target_broke or has_extra_regressions:
                # Either none of the combined failures are the own target's
                # (own_target_broke is False), or the own target broke *and*
                # something else also failed — label every failure that
                # isn't one of the own target's as a regression, in both
                # cases, instead of only when the own target is entirely
                # clean.
                own_failure_names = {f["name"] for f in own_result.failures}
                result.failures = [
                    f
                    if own_target_broke and f["name"] in own_failure_names
                    else {"name": f"REGRESSION: {f['name']}", "message": f["message"]}
                    for f in result.failures
                ]

        capped_failures = _cap_failures(result.failures)

        self.sm.record_test_result(
            passed=result.passed,
            failed=result.failed,
            duration_ms=result.duration_ms,
            failures=capped_failures,
            raw_output=result.raw_output,
        )
        self._log_event(
            "run_tests",
            passed=result.passed,
            failed=result.failed,
            durationMs=result.duration_ms,
        )

        if own_target_broke is False:
            # record_test_result's generic REFACTOR-failure message ("Refactor
            # broke the tests.") is wrong here — this cycle's own test passed;
            # the failure came from elsewhere in the suite.
            self.sm.set_last_error(
                "Regression check found pre-existing failures elsewhere "
                "(not caused by this refactor) — see the REGRESSION: "
                "entries in failures."
            )
        elif own_target_broke and has_extra_regressions:
            # Both problems are real here — say so, rather than letting the
            # generic "Refactor broke the tests." message imply that fixing
            # the own test is all that's needed.
            self.sm.set_last_error(
                "Refactor broke the tests, and the regression check also "
                "found pre-existing failures elsewhere (not caused by this "
                "refactor) — see the REGRESSION: entries in failures."
            )

        return {
            "testResult": {
                "passed": result.passed,
                "failed": result.failed,
                "durationMs": result.duration_ms,
                "failures": capped_failures,
            },
            **self.sm.status(),
        }


def build_server() -> Server:
    tdd = TDDServer(PROJECT_ROOT, CONFIG_PATH)
    server: Server = Server("outside-in-tdd")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent]:
        return tdd.call_tool(name, arguments or {})

    return server


async def main() -> None:
    server = build_server()
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="outside-in-tdd",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def run() -> None:
    """Sync entry point for the `outside-in-tdd-mcp` console script."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
