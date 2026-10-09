import json
import subprocess
import threading

import pytest

from core.review_runner import ReviewManager

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


def pi_stream(text, stop_reason="stop", settled=True):
    events = [
        {"type": "agent_start"},
        {"type": "message_end", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "stopReason": stop_reason}},
    ]
    if settled:
        events.append({"type": "agent_settled", "aborted": False})
    return "\n".join(json.dumps(e) for e in events) + "\n"


def findings_reply(*findings):
    return pi_stream("```json\n" + json.dumps({"findings": list(findings)}) + "\n```")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    return tmp_path


def make_manager(repo, runner, config=None):
    return ReviewManager(
        project_root=str(repo),
        findings_path=str(repo / ".tdd-review-findings.json"),
        config=config or {},
        runner=runner,
    )


def test_a_successful_review_is_done_with_findings_tagged_and_stored(repo):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    seen = {}

    def runner(argv, cwd):
        seen["argv"], seen["cwd"] = argv, cwd
        return findings_reply(FINDING)

    manager = make_manager(repo, runner)
    review_id = manager.start(f"{first}..HEAD", model="openai/m")

    result = manager.await_result(review_id, timeout=10)

    expected = {**FINDING, "status": "open", "reviewer": "pi", "model": "openai/m"}
    assert result == {"status": "done", "scope": f"review:{first}", "findings": [expected]}
    assert seen["cwd"] == str(repo)
    assert "+b.py" in seen["argv"][-1]  # the diff reached the prompt


@pytest.mark.parametrize(
    "reply, expected_error",
    [
        (pi_stream("no json here", settled=False), "agent_settled"),
        (pi_stream("", stop_reason="error"), "did not finish cleanly"),
        (pi_stream("I found nothing, looks fine."), "findings block"),
    ],
)
def test_a_failed_review_reports_failed_and_stores_nothing(repo, reply, expected_error):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    manager = make_manager(repo, lambda argv, cwd: reply)

    review_id = manager.start(f"{first}..HEAD")
    result = manager.await_result(review_id, timeout=10)

    assert result["status"] == "failed"
    assert expected_error in result["error"]
    assert "findings" not in result
    assert not (repo / ".tdd-review-findings.json").exists()


def counting_runner(*replies):
    calls = []
    remaining = list(replies)

    def runner(argv, cwd):
        calls.append(argv)
        return remaining.pop(0)

    runner.calls = calls
    return runner


def test_malformed_findings_are_retried_exactly_once(repo):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    bad = pi_stream("sorry, no json")

    recovers = counting_runner(bad, findings_reply(FINDING))
    manager = make_manager(repo, recovers)
    result = manager.await_result(manager.start(f"{first}..HEAD"), timeout=10)
    assert result["status"] == "done" and len(recovers.calls) == 2

    gives_up = counting_runner(bad, bad, findings_reply(FINDING))
    manager = make_manager(repo, gives_up)
    result = manager.await_result(manager.start(f"{first}..HEAD"), timeout=10)
    assert result["status"] == "failed" and len(gives_up.calls) == 2


def test_a_pi_level_failure_is_not_retried(repo):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    runner = counting_runner(pi_stream("x", settled=False), findings_reply(FINDING))
    manager = make_manager(repo, runner)

    result = manager.await_result(manager.start(f"{first}..HEAD"), timeout=10)

    assert result["status"] == "failed" and len(runner.calls) == 1


def test_start_returns_immediately_and_await_reports_pending_until_the_reviewer_finishes(repo):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    release = threading.Event()

    def slow_runner(argv, cwd):
        assert release.wait(timeout=10), "test never released the reviewer"
        return findings_reply(FINDING)

    manager = make_manager(repo, slow_runner)

    review_id = manager.start(f"{first}..HEAD")  # must not block on the reviewer

    assert manager.await_result(review_id, timeout=0.1) == {"status": "pending"}
    release.set()
    assert manager.await_result(review_id, timeout=10)["status"] == "done"


def test_an_invalid_range_fails_immediately_without_starting_a_review(repo):
    commit(repo, "a.py")
    runner = counting_runner()
    manager = make_manager(repo, runner)

    with pytest.raises(ValueError, match="Unknown revision 'deadbeef'"):
        manager.start("deadbeef..HEAD")

    assert runner.calls == []


def test_awaiting_an_unknown_review_id_raises_a_clear_error(repo):
    manager = make_manager(repo, counting_runner())

    with pytest.raises(ValueError, match="Unknown review id 'nope'"):
        manager.await_result("nope", timeout=0)


def test_findings_are_written_while_holding_the_supplied_findings_lock(repo):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    events = []

    class RecordingLock:
        def __enter__(self):
            events.append("enter")

        def __exit__(self, *exc):
            events.append("exit")

    manager = ReviewManager(
        project_root=str(repo),
        findings_path=str(repo / ".tdd-review-findings.json"),
        config={},
        runner=lambda argv, cwd: findings_reply(FINDING),
        findings_lock=RecordingLock,
    )

    result = manager.await_result(manager.start(f"{first}..HEAD"), timeout=10)

    assert result["status"] == "done"
    assert events == ["enter", "exit"]


def test_a_completed_review_is_recorded_as_a_round_but_a_failed_one_is_not(repo):
    from core.review_rounds import list_rounds

    first = commit(repo, "a.py")
    head = commit(repo, "b.py")
    rounds_path = str(repo / ".tdd-review-rounds.json")
    manager = make_manager(
        repo, counting_runner(findings_reply(FINDING), pi_stream("x", settled=False))
    )

    ok = manager.await_result(manager.start(f"{first}..HEAD", model="openai/m"), timeout=10)
    bad = manager.await_result(manager.start(f"{first}..HEAD"), timeout=10)

    assert (ok["status"], bad["status"]) == ("done", "failed")
    [round_one] = list_rounds(f"review:{first}", path=rounds_path)
    assert (round_one["round"], round_one["start"], round_one["head"]) == (1, first, head)
    assert (round_one["reviewer"], round_one["model"]) == ("pi", "openai/m")
    assert round_one["findings"] == ok["findings"]
