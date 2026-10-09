import json
import os
import shutil
import subprocess
import sys

import pytest

from core.server import TDDServer

FINDING = {
    "id": "missing-lock",
    "severity": "high",
    "file": "a.py",
    "line": 1,
    "claim": "Concurrent writes can lose findings",
    "suggestion": "Take the lock",
}


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo, name):
    (repo / name).write_text(name + "\n")
    git(repo, "add", name)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com",
        "commit", "-q", "-m", name)
    return git(repo, "rev-parse", "HEAD")


def pi_stream(text, stop_reason="stop"):
    events = [
        {"type": "agent_start"},
        {"type": "message_end", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "stopReason": stop_reason}},
        {"type": "agent_settled", "aborted": False},
    ]
    return "\n".join(json.dumps(e) for e in events) + "\n"


def findings_reply(*findings):
    return pi_stream("```json\n" + json.dumps({"findings": list(findings)}) + "\n```")


class FakeRunner:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, argv, cwd):
        self.calls.append(argv)
        return self.replies.pop(0)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    return tmp_path


def make_server(repo, runner):
    config_path = repo / ".tdd-config.json"
    config_path.write_text(json.dumps({"adapterPath": "pytest-adapter-runner"}))
    return TDDServer(
        project_root=str(repo), config_path=str(config_path), review_runner=runner
    )


def call(server, name, **arguments):
    return json.loads(server.call_tool(name, arguments)[0].text)


def test_start_then_await_review_returns_findings_saved_under_the_range_scope(repo):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    runner = FakeRunner(findings_reply(FINDING))
    server = make_server(repo, runner)

    started = call(server, "start_review", range=f"{first}..HEAD",
                   reviewer="pi", model="openai/test-model")
    result = call(server, "await_review", reviewId=started["reviewId"],
                  timeoutSeconds=10)

    assert result["status"] == "done"
    assert result["findings"] == [
        {**FINDING, "status": "open", "reviewer": "pi", "model": "openai/test-model"}
    ]
    stored = call(server, "list_review_findings", scope=f"review:{first}")
    assert stored["findings"] == result["findings"]
    assert "openai/test-model" in runner.calls[0]


def fake_pi_on_path(tmp_path, monkeypatch, stdout, exit_code=0):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pi = bin_dir / "pi"
    pi.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stdout.write({stdout!r})\nsys.exit({exit_code})\n"
    )
    pi.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_without_an_injected_runner_the_server_spawns_pi_from_the_path(
    repo, monkeypatch
):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    # pi can exit non-zero even after a good run; the event stream decides.
    fake_pi_on_path(repo, monkeypatch, findings_reply(FINDING), exit_code=1)
    server = make_server(repo, runner=None)

    started = call(server, "start_review", range=f"{first}..HEAD")
    result = call(server, "await_review", reviewId=started["reviewId"], timeoutSeconds=10)

    assert result["status"] == "done"
    assert [f["id"] for f in result["findings"]] == ["missing-lock"]


def test_a_missing_reviewer_binary_is_reported_as_a_failed_review(repo, monkeypatch):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    # git must stay reachable (start_review runs it); pi must not be.
    monkeypatch.setenv("PATH", os.path.dirname(shutil.which("git")))
    assert shutil.which("pi") is None, "pi unexpectedly lives next to git"
    server = make_server(repo, runner=None)

    started = call(server, "start_review", range=f"{first}..HEAD")
    result = call(server, "await_review", reviewId=started["reviewId"], timeoutSeconds=10)

    assert result["status"] == "failed"
    assert "pi" in result["error"]


def test_a_blocking_await_review_does_not_freeze_the_servers_event_loop():
    import asyncio
    import time

    from core.server import _dispatch_tool

    class SlowTdd:
        def call_tool(self, name, arguments):
            time.sleep(0.4)  # stands in for await_review waiting on a reviewer
            return [name]

    async def scenario():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        task = asyncio.create_task(ticker())
        result = await _dispatch_tool(SlowTdd(), "await_review", {})
        task.cancel()
        return result, ticks

    result, ticks = asyncio.run(scenario())

    assert result == ["await_review"]
    assert ticks >= 5, f"event loop was blocked (only {ticks} ticks)"


def test_review_tool_errors_come_back_as_error_payloads_not_exceptions(repo):
    commit(repo, "a.py")
    server = make_server(repo, FakeRunner())

    bad_range = call(server, "start_review", range="deadbeef..HEAD")
    malformed = call(server, "start_review", range="HEAD")
    unknown_before_any_review = call(server, "await_review", reviewId="nope")
    call(server, "start_review", range=f"{commit(repo, 'b.py')[:7]}..HEAD")
    unknown_after = call(server, "await_review", reviewId="nope")

    assert bad_range == {"error": "Unknown revision 'deadbeef'"}
    assert "Expected a range like '<sha>..HEAD'" in malformed["error"]
    assert unknown_before_any_review == {"error": "Unknown review id 'nope'"}
    assert unknown_after == {"error": "Unknown review id 'nope'"}


def test_start_review_is_refused_while_a_tdd_feature_is_in_progress(repo):
    from pathlib import Path

    first = commit(repo, "a.py")
    commit(repo, "b.py")
    runner = FakeRunner(findings_reply(FINDING))
    server = make_server(repo, runner)
    adapter = Path(__file__).resolve().parents[1] / "adapters/pytest-adapter/run.sh"
    (repo / ".tdd-config.json").write_text(json.dumps({"adapterPath": str(adapter)}))
    call(server, "init_feature", featureName="half-done", testFile="t.py", targetFiles=[])

    blocked = call(server, "start_review", range=f"{first}..HEAD")

    assert blocked == {
        "error": (
            "Can't start a review while feature 'half-done' is in progress — "
            "finish it with complete_feature (or reset_feature) first, so the "
            "reviewer only sees completed work."
        )
    }
    assert runner.calls == []


def test_each_completed_review_is_recorded_as_a_numbered_round(repo):
    first = commit(repo, "a.py")
    head = commit(repo, "b.py")
    server = make_server(repo, FakeRunner(findings_reply(FINDING), pi_stream("garbage")))

    done = call(server, "start_review", range=f"{first}..HEAD", model="openai/m")
    call(server, "await_review", reviewId=done["reviewId"], timeoutSeconds=10)
    commit(repo, "c.py")
    failed = call(server, "start_review", range=f"{head}..HEAD")  # fails: not recorded
    assert call(server, "await_review", reviewId=failed["reviewId"], timeoutSeconds=10)["status"] == "failed"

    rounds = call(server, "list_review_rounds", scope=f"review:{first}")["rounds"]

    assert len(rounds) == 1
    assert {k: rounds[0][k] for k in ("round", "start", "head", "reviewer", "model")} == {
        "round": 1, "start": first, "head": head, "reviewer": "pi", "model": "openai/m",
    }
    assert [f["id"] for f in rounds[0]["findings"]] == ["missing-lock"]
    assert "recordedAt" in rounds[0]


def test_review_rounds_file_is_added_to_git_info_exclude(repo):
    (repo / ".git" / "info").mkdir(parents=True, exist_ok=True)
    server = make_server(repo, FakeRunner())

    call(server, "init_feature", featureName="f", testFile="t.py", targetFiles=[])
    call(server, "reset_feature")

    lines = (repo / ".git" / "info" / "exclude").read_text().splitlines()
    assert lines.count(".tdd-review-rounds.json") == 1


LOW_FINDING = {**FINDING, "id": "nit", "severity": "low"}


def run_review(server, start):
    started = call(server, "start_review", range=f"{start}..HEAD")
    return call(server, "await_review", reviewId=started["reviewId"], timeoutSeconds=10)


def test_a_round_decides_continue_with_open_blocking_findings_and_done_without(repo):
    first = commit(repo, "a.py")
    second = commit(repo, "b.py")
    commit(repo, "c.py")
    server = make_server(repo, FakeRunner(
        findings_reply(FINDING, LOW_FINDING), findings_reply(LOW_FINDING)))

    blocking = run_review(server, first)
    only_low = run_review(server, second)

    assert blocking["decision"] == "continue"
    assert only_low["decision"] == "done"


def test_a_finding_rejected_twice_that_comes_back_escalates_to_the_human(repo):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    server = make_server(repo, FakeRunner(findings_reply(FINDING)))
    scope = f"review:{first}"
    for _ in range(2):
        call(server, "record_review_finding", scope=scope,
             finding={**FINDING, "status": "rejected", "reason": "by design"})

    result = run_review(server, first)

    assert result["decision"] == "escalate"
    assert "missing-lock" in result["reason"]


OTHER_FINDING = {**FINDING, "id": "bad-name", "severity": "medium"}


def test_a_repeat_review_of_the_same_start_reviews_only_new_commits_with_the_ledger(repo):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    runner = FakeRunner(findings_reply(FINDING, OTHER_FINDING), findings_reply())
    server = make_server(repo, runner)
    scope = f"review:{first}"
    run_review(server, first)
    # The author fixed one finding (complete_feature drops it from the live
    # store) and rejected the other with a reason.
    store = repo / ".tdd-review-findings.json"
    live = json.loads(store.read_text())
    live[scope] = [f for f in live[scope] if f["id"] != "missing-lock"]
    store.write_text(json.dumps(live))
    call(server, "record_review_finding", scope=scope,
         finding={**OTHER_FINDING, "status": "rejected", "reason": "by design"})
    commit(repo, "c.py")

    second = run_review(server, first)

    prompt = runner.calls[1][-1]
    assert second["status"] == "done"
    assert "+c.py" in prompt and "+b.py" not in prompt
    start = prompt.index("[\n", prompt.index("Previous findings"))
    ledger = json.loads(prompt[start:prompt.index("\n```", start)])
    assert {(f["id"], f["status"]) for f in ledger} == {
        ("missing-lock", "fixed"), ("bad-name", "rejected")}
    assert [r["round"] for r in call(server, "list_review_rounds", scope=scope)["rounds"]] == [1, 2]


def test_a_repeat_review_with_no_new_commits_since_the_last_round_is_an_error(repo):
    first = commit(repo, "a.py")
    head = commit(repo, "b.py")
    runner = FakeRunner(findings_reply(FINDING))
    server = make_server(repo, runner)
    run_review(server, first)

    again = call(server, "start_review", range=f"{first}..HEAD")

    assert again == {
        "error": f"No new commits since the last review round (HEAD is {head[:7]}) — "
                 "commit the fixes first."
    }
    assert len(runner.calls) == 1
