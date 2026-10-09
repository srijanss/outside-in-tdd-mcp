import subprocess
import threading
import uuid
from contextlib import nullcontext
from pathlib import Path

from core.pi_events import parse_pi_events
from core.review_decision import decide
from core.review_findings import list_review_findings, record_review_finding
from core.review_findings_parser import FindingsParseError, parse_findings
from core.review_prompt import build_review_prompt
from core.review_range import resolve_review_range
from core.review_rounds import record_round
from core.reviewers import build_reviewer_command


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

    def start(self, range_spec, reviewer=None, model=None, thinking=None) -> str:
        resolved = resolve_review_range(range_spec, repo=self.project_root)
        diff = subprocess.run(
            ["git", "diff", f"{resolved['start']}..{resolved['head']}"],
            cwd=self.project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        command = build_reviewer_command(
            build_review_prompt(diff),
            reviewer=reviewer,
            model=model,
            thinking=thinking,
            config=self.config,
        )
        review_id = uuid.uuid4().hex
        self._reviews[review_id] = {"done": threading.Event(), "result": None}
        threading.Thread(
            target=self._job,
            args=(review_id, command, resolved),
            daemon=True,
        ).start()
        return review_id

    def _job(self, review_id, command, resolved) -> None:
        review = self._reviews[review_id]
        try:
            review["result"] = self._run(command, resolved)
        except Exception as exc:  # e.g. the findings store itself failing
            review["result"] = {"status": "failed", "error": str(exc)}
        finally:
            review["done"].set()

    def _run(self, command, resolved) -> dict:
        scope = f"review:{resolved['start']}"
        # Any failure must end in a terminal "failed" result: a review that
        # errors out must never look like one that found nothing.
        try:
            try:
                findings = self._review_once(command)
            except FindingsParseError:
                # Models occasionally botch the JSON; one retry is cheap.
                # Pi-level failures are not retried.
                findings = self._review_once(command)
        except Exception as exc:
            return {"status": "failed", "error": str(exc)}

        tagged = [
            {
                **finding,
                "status": "open",
                "reviewer": command["reviewer"],
                "model": command["model"],
            }
            for finding in findings
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

    def _review_once(self, command) -> list[dict]:
        output = self.runner(command["argv"], self.project_root)
        return parse_findings(parse_pi_events(output)["text"])

    def await_result(self, review_id, timeout):
        review = self._reviews.get(review_id)
        if review is None:
            raise ValueError(f"Unknown review id '{review_id}'")
        if not review["done"].wait(timeout):
            return {"status": "pending"}
        return review["result"]
