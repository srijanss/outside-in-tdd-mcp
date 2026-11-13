import subprocess
import threading
import uuid
from contextlib import nullcontext
from pathlib import Path

from core.claude_output import ClaudeReviewError, parse_claude_output
from core.pi_events import PiReviewError, parse_pi_events
from core.review_decision import decide
from core.review_findings import list_review_findings, record_review_finding
from core.review_findings_parser import CATEGORIES, FindingsParseError, parse_findings
from core.review_prompt import build_review_prompt
from core.review_range import resolve_review_range
from core.review_rounds import list_rounds, record_round
from core.reviewers import (
    ReviewerProcessError,
    build_reviewer_command,
    fallback_models,
    is_quota_or_access_error,
)


def _ledger(rounds: list[dict], live: list[dict]) -> list[dict]:
    """Every finding raised in earlier rounds with its current status.
    Fixed findings are deleted from the live store, so a finding that was
    reported but is no longer there counts as fixed."""
    live_by_id = {f["id"]: f for f in live}
    reported: dict[str, dict] = {}
    for round_entry in rounds:
        for finding in round_entry["findings"]:
            reported[finding["id"]] = finding
    ledger = []
    for finding_id, finding in reported.items():
        current = live_by_id.get(finding_id)
        entry = {k: finding[k] for k in ("id", "severity", "file", "line", "claim")}
        entry["status"] = current["status"] if current else "fixed"
        if current and current.get("reason"):
            entry["reason"] = current["reason"]
        ledger.append(entry)
    return ledger


def review_scope(start: str, categories=None) -> str:
    """The findings/rounds scope of a review of ``start``. Each category
    subset keeps its own round history: rounds only review what changed since
    the last round, so a subset sharing the full review's history would never
    check the earlier commits for the categories it skipped."""
    if categories is None or set(CATEGORIES) <= set(categories):
        return f"review:{start}"
    wanted = ",".join(c for c in CATEGORIES if c in categories)
    return f"review:{start}[{wanted}]"


# Errors the reviewer itself reported, as opposed to local failures that a
# different model cannot fix.
REVIEWER_ERRORS = (PiReviewError, ClaudeReviewError, ReviewerProcessError)


def _model_unavailable(exc: Exception) -> bool:
    return isinstance(exc, REVIEWER_ERRORS) and is_quota_or_access_error(str(exc))


class ReviewManager:
    def __init__(
        self,
        project_root,
        findings_path,
        config,
        runner,
        findings_lock=nullcontext,
        rounds_path=None,
    ):
        self.project_root = project_root
        self.findings_path = findings_path
        self.rounds_path = rounds_path or str(
            Path(findings_path).with_name(".tdd-review-rounds.json")
        )
        self.config = config
        self.runner = runner
        # Factory for a context manager guarding findings_path; the server
        # passes its file lock since jobs write from background threads.
        self.findings_lock = findings_lock
        self._reviews: dict[str, dict] = {}
        # What await_review waits on when it isn't given a reviewId.
        self.latest_review_id: str | None = None
        # What list_review_findings lists when it isn't given a scope.
        self.latest_review_scope: str | None = None
        self._in_flight: set[str] = set()
        self._in_flight_lock = threading.Lock()

    def start(
        self, range_spec, reviewer=None, model=None, thinking=None, categories=None
    ) -> str:
        """categories: the subset of review categories to ask for and keep
        (all when None)."""
        resolved = resolve_review_range(range_spec, repo=self.project_root)
        scope = review_scope(resolved["start"], categories)
        # Rounds are chained (each diff starts at the last round's head), so
        # two reviews of one scope in flight would record out of order.
        with self._in_flight_lock:
            if scope in self._in_flight:
                raise ValueError(
                    f"A review of {scope} is already in progress — "
                    "await it before starting the next round."
                )
            self._in_flight.add(scope)
        try:
            review_id, commands = self._prepare(
                scope, resolved, reviewer, model, thinking, categories
            )
            threading.Thread(
                target=self._job,
                args=(review_id, commands, resolved, scope, categories),
                daemon=True,
            ).start()
        except BaseException:
            self._release(scope)
            raise
        self.latest_review_id = review_id
        self.latest_review_scope = scope
        return review_id

    def _release(self, scope) -> None:
        with self._in_flight_lock:
            self._in_flight.discard(scope)

    def _prepare(self, scope, resolved, reviewer, model, thinking, categories):
        with self.findings_lock():
            rounds = list_rounds(scope, path=self.rounds_path)
            live = list_review_findings(scope, path=self.findings_path)
        # A repeat of the same range is the next fix round: only review what
        # changed since the last round, and tell the reviewer what happened
        # to its earlier findings.
        base = rounds[-1]["head"] if rounds else resolved["start"]
        if base == resolved["head"]:
            raise ValueError(
                "No new commits since the last review round "
                f"(HEAD is {base[:7]}) — commit the fixes first."
            )
        diff = subprocess.run(
            ["git", "diff", f"{base}..{resolved['head']}"],
            cwd=self.project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        prompt = build_review_prompt(
            diff, ledger=_ledger(rounds, live), categories=categories
        )
        primary = build_reviewer_command(
            prompt, reviewer=reviewer, model=model, thinking=thinking,
            config=self.config,
        )
        # Tried in order, moving on only after a quota/access error.
        commands = [primary] + [
            build_reviewer_command(
                prompt, reviewer=primary["reviewer"], model=fallback,
                thinking=primary["thinking"], config=self.config,
            )
            for fallback in fallback_models(self.config, primary["model"])
        ]
        review_id = uuid.uuid4().hex
        self._reviews[review_id] = {"done": threading.Event(), "result": None}
        return review_id, commands

    def _job(self, review_id, commands, resolved, scope, categories) -> None:
        review = self._reviews[review_id]
        try:
            review["result"] = self._run(commands, resolved, scope, categories)
        except Exception as exc:  # e.g. the findings store itself failing
            review["result"] = {"status": "failed", "error": str(exc)}
        finally:
            self._release(scope)
            review["done"].set()

    def _run(self, commands, resolved, scope, categories) -> dict:
        # Any failure must end in a terminal "failed" result: a review that
        # errors out must never look like one that found nothing.
        failures = []
        for command in commands:
            try:
                findings = self._review_with_retry(command)
                break
            except Exception as exc:
                failures.append(f"{command['model'] or 'default model'}: {exc}")
                if command is commands[-1] or not _model_unavailable(exc):
                    error = "; ".join(failures) if len(failures) > 1 else str(exc)
                    return {"status": "failed", "error": error}

        tagged = [
            {
                **finding,
                "status": "open",
                "reviewer": command["reviewer"],
                "model": command["model"],
            }
            for finding in findings
            # Findings outside the requested categories were not asked for.
            if categories is None or finding["category"] in categories
        ]
        with self.findings_lock():
            for finding in tagged:
                record_review_finding(scope, finding, path=self.findings_path)
            round_entry = record_round(
                scope,
                {
                    "start": resolved["start"],
                    "head": resolved["head"],
                    "reviewer": command["reviewer"],
                    "model": command["model"],
                    "findings": tagged,
                },
                path=self.rounds_path,
            )
            live = list_review_findings(scope, path=self.findings_path)
        return {
            "status": "done",
            "scope": scope,
            "findings": tagged,
            **decide(round_entry["round"], live),
        }

    def _review_with_retry(self, command) -> list[dict]:
        try:
            return self._review_once(command)
        except FindingsParseError:
            # Models occasionally botch the JSON; one retry is cheap.
            # Pi-level failures are not retried.
            return self._review_once(command)

    def _review_once(self, command) -> list[dict]:
        output = self.runner(command["argv"], self.project_root, command["stdin"])
        parse_output = (
            parse_claude_output if command["reviewer"] == "claude" else parse_pi_events
        )
        return parse_findings(parse_output(output)["text"])

    def await_result(self, review_id, timeout):
        review = self._reviews.get(review_id)
        if review is None:
            raise ValueError(f"Unknown review id '{review_id}'")
        if not review["done"].wait(timeout):
            return {"status": "pending"}
        return review["result"]
