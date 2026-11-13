import json
import subprocess
import threading

import pytest

from core.review_runner import ReviewManager

FINDING = {
    "id": "missing-lock",
    "severity": "high",
    "category": "bugs",
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

    def runner(argv, cwd, stdin):
        seen["argv"], seen["cwd"], seen["stdin"] = argv, cwd, stdin
        return findings_reply(FINDING)

    manager = make_manager(repo, runner)
    review_id = manager.start(f"{first}..HEAD", model="openai/m")

    result = manager.await_result(review_id, timeout=10)

    expected = {**FINDING, "status": "open", "reviewer": "pi", "model": "openai/m"}
    assert result == {"status": "done", "scope": f"review:{first}", "findings": [expected], "decision": "continue"}
    assert seen["cwd"] == str(repo)
    assert "+b.py" in seen["stdin"]  # the diff reached the prompt


def test_the_review_prompt_with_the_diff_is_passed_to_the_runner_as_stdin_not_argv(repo):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    seen = {}

    def runner(argv, cwd, stdin):
        seen["argv"], seen["stdin"] = argv, stdin
        return findings_reply()

    manager = make_manager(repo, runner)
    review_id = manager.start(f"{first}..HEAD")
    manager.await_result(review_id, timeout=10)

    assert "+++ b/b.py" in seen["stdin"]
    assert not any("+++ b/b.py" in arg for arg in seen["argv"])


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
    manager = make_manager(repo, lambda argv, cwd, stdin: reply)

    review_id = manager.start(f"{first}..HEAD")
    result = manager.await_result(review_id, timeout=10)

    assert result["status"] == "failed"
    assert expected_error in result["error"]
    assert "findings" not in result
    assert not (repo / ".tdd-review-findings.json").exists()


def counting_runner(*replies):
    calls = []
    remaining = list(replies)

    def runner(argv, cwd, stdin):
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

    commit(repo, "c.py")  # a repeat of the same range would be a fix round
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

    def slow_runner(argv, cwd, stdin):
        assert release.wait(timeout=10), "test never released the reviewer"
        return findings_reply(FINDING)

    manager = make_manager(repo, slow_runner)

    review_id = manager.start(f"{first}..HEAD")  # must not block on the reviewer

    assert manager.await_result(review_id, timeout=0.1) == {"status": "pending"}
    release.set()
    assert manager.await_result(review_id, timeout=10)["status"] == "done"


def test_a_second_review_of_a_scope_is_refused_while_one_is_in_flight(repo):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    release = threading.Event()

    def slow_runner(argv, cwd, stdin):
        assert release.wait(timeout=10), "test never released the reviewer"
        return findings_reply(FINDING)

    manager = make_manager(repo, slow_runner)
    review_id = manager.start(f"{first}..HEAD")
    commit(repo, "c.py")

    with pytest.raises(ValueError, match="already in progress"):
        manager.start(f"{first}..HEAD")

    release.set()
    assert manager.await_result(review_id, timeout=10)["status"] == "done"
    # Once the first round has finished the next one may start.
    assert manager.start(f"{first}..HEAD")


def test_a_scope_can_be_reviewed_again_after_start_fails_during_preparation(repo):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    manager = make_manager(repo, lambda argv, cwd, stdin: findings_reply())
    manager.await_result(manager.start(f"{first}..HEAD"), timeout=10)

    with pytest.raises(ValueError, match="No new commits"):
        manager.start(f"{first}..HEAD")
    commit(repo, "c.py")

    retry = manager.start(f"{first}..HEAD")
    assert manager.await_result(retry, timeout=10)["status"] == "done"


def test_a_scope_can_be_reviewed_again_after_a_background_review_fails(repo):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    manager = make_manager(
        repo, lambda argv, cwd, stdin: pi_stream("", stop_reason="error")
    )
    failed = manager.start(f"{first}..HEAD")
    assert manager.await_result(failed, timeout=10)["status"] == "failed"

    manager.runner = lambda argv, cwd, stdin: findings_reply()
    retry = manager.start(f"{first}..HEAD")

    assert manager.await_result(retry, timeout=10)["status"] == "done"


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
        runner=lambda argv, cwd, stdin: findings_reply(FINDING),
        findings_lock=RecordingLock,
    )

    result = manager.await_result(manager.start(f"{first}..HEAD"), timeout=10)

    assert result["status"] == "done"
    # once to read the round history, once to save findings and the round
    assert events == ["enter", "exit", "enter", "exit"]


def test_a_completed_review_is_recorded_as_a_round_but_a_failed_one_is_not(repo):
    from core.review_rounds import list_rounds

    first = commit(repo, "a.py")
    head = commit(repo, "b.py")
    rounds_path = str(repo / ".tdd-review-rounds.json")
    manager = make_manager(
        repo, counting_runner(findings_reply(FINDING), pi_stream("x", settled=False))
    )

    ok = manager.await_result(manager.start(f"{first}..HEAD", model="openai/m"), timeout=10)
    commit(repo, "c.py")
    bad = manager.await_result(manager.start(f"{head}..HEAD"), timeout=10)

    assert (ok["status"], bad["status"]) == ("done", "failed")
    [round_one] = list_rounds(f"review:{first}", path=rounds_path)
    assert (round_one["round"], round_one["start"], round_one["head"]) == (1, first, head)
    assert (round_one["reviewer"], round_one["model"]) == ("pi", "openai/m")
    assert round_one["findings"] == ok["findings"]


def test_a_review_for_some_categories_asks_for_and_keeps_only_those(repo):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    leak = {**FINDING, "id": "token-in-log", "category": "security"}
    stdins = []

    def runner(argv, cwd, stdin):
        stdins.append(stdin)
        return findings_reply(FINDING, leak)

    manager = make_manager(repo, runner)
    review_id = manager.start(f"{first}..HEAD", categories=["security"])
    result = manager.await_result(review_id, timeout=10)

    assert [f["id"] for f in result["findings"]] == ["token-in-log"]
    assert "missing-tests" not in stdins[0]
    rounds = json.loads((repo / ".tdd-review-rounds.json").read_text())
    [round_entry] = rounds[f"review:{first}[security]"]
    assert [f["id"] for f in round_entry["findings"]] == ["token-in-log"]


@pytest.mark.parametrize(
    "categories, suffix",
    [
        (None, ""),
        (["security", "bugs"], "[bugs,security]"),
        (["performance", "security", "missing-tests", "bugs"], ""),
    ],
)
def test_each_category_subset_keeps_its_own_round_history(repo, categories, suffix):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    manager = make_manager(repo, lambda argv, cwd, stdin: findings_reply())

    review_id = manager.start(f"{first}..HEAD", categories=categories)
    result = manager.await_result(review_id, timeout=10)

    # Subsets are named in canonical order; all four is the plain scope.
    assert result["scope"] == f"review:{first}{suffix}"
    assert manager.latest_review_scope == result["scope"]
    rounds = json.loads((repo / ".tdd-review-rounds.json").read_text())
    assert list(rounds) == [result["scope"]]


def test_switching_categories_between_rounds_reviews_each_subset_from_the_start(repo):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    stdins = []

    def runner(argv, cwd, stdin):
        stdins.append(stdin)
        return findings_reply()

    manager = make_manager(repo, runner)

    def review(categories):
        review_id = manager.start(f"{first}..HEAD", categories=categories)
        return manager.await_result(review_id, timeout=10)

    review(["security"])
    # Unchanged HEAD: another subset and the full review still run, on the
    # whole range; a repeat of the same subset is refused.
    review(["bugs"])
    review(None)
    with pytest.raises(ValueError, match="No new commits"):
        manager.start(f"{first}..HEAD", categories=["security"])
    commit(repo, "c.py")
    # A new commit: the repeated subsets review only it, a new subset
    # reviews everything.
    review(["security"])
    review(None)
    review(["performance"])

    whole = ["+b.py" in s and "+c.py" not in s for s in stdins[:3]]
    assert whole == [True, True, True]
    assert ["+b.py" in s for s in stdins[3:]] == [False, False, True]
    assert all("+c.py" in s for s in stdins[3:])
    rounds = json.loads((repo / ".tdd-review-rounds.json").read_text())
    assert {scope: len(r) for scope, r in rounds.items()} == {
        f"review:{first}[security]": 2,
        f"review:{first}[bugs]": 1,
        f"review:{first}": 2,
        f"review:{first}[performance]": 1,
    }


def pi_error(message):
    events = [
        {"type": "message_end", "message": {
            "role": "assistant", "content": [], "stopReason": "error",
            "errorMessage": message}},
        {"type": "agent_settled", "aborted": False},
    ]
    return "\n".join(json.dumps(e) for e in events) + "\n"


def claude_error(message):
    return json.dumps({"type": "result", "subtype": "success", "is_error": True,
                       "result": message})


FALLBACK_CONFIG = {"reviewers": {"default": {"model": "m/a"},
                                 "fallbackModels": ["m/a", "m/b"]}}


@pytest.mark.parametrize(
    "reviewer, replies, expected",
    [
        # Only quota/access errors move on to the next model.
        ("pi", [pi_error("connection reset by peer")],
         {"status": "failed", "calls": ["m/a"], "error": ["connection reset"]}),
        # Every model out of quota: the error names each attempt.
        ("pi", [pi_error("429 rate limit exceeded"), pi_error("insufficient_quota")],
         {"status": "failed", "calls": ["m/a", "m/b"],
          "error": ["m/a", "rate limit", "m/b", "insufficient_quota"]}),
        ("claude", [claude_error("Credit balance is too low"),
                    json.dumps({"type": "result", "subtype": "success",
                                "is_error": False, "terminal_reason": "completed",
                                "result": '```json\n{"findings": []}\n```'})],
         {"status": "done", "calls": ["m/a", "m/b"]}),
        ("pi", [pi_error("403 Forbidden: no access to model m/a"),
                pi_stream("not json"), findings_reply()],
         {"status": "done", "calls": ["m/a", "m/b", "m/b"]}),
    ],
)
def test_only_quota_or_access_errors_fall_back_to_the_next_model(
    repo, reviewer, replies, expected
):
    first = commit(repo, "a.py")
    commit(repo, "b.py")
    calls = []

    def runner(argv, cwd, stdin):
        calls.append(argv[argv.index("--model") + 1])
        return replies.pop(0)

    manager = make_manager(repo, runner, config=FALLBACK_CONFIG)
    result = manager.await_result(
        manager.start(f"{first}..HEAD", reviewer=reviewer), timeout=10)

    assert result["status"] == expected["status"]
    assert calls == expected["calls"]
    for fragment in expected.get("error", []):
        assert fragment in result["error"]


@pytest.mark.parametrize(
    "first_reply, calls",
    [
        # Local failures switching models cannot fix.
        (PermissionError("[Errno 13] Permission denied: '/repo/.git'"), 1),
        (OSError("insufficient disk space"), 1),
        (RuntimeError("could not access the repository: 403"), 1),
        # A reviewer error that isn't about quota or access.
        (pi_error("insufficient disk space to write the session"), 1),
        (pi_error("permission to run tool bash denied"), 1),
        # The reviewer process itself reporting a provider quota error.
        ("process:pi exited 1 with no output: Error: 429 quota exceeded", 2),
    ],
)
def test_only_provider_reported_quota_or_access_errors_fall_back(
    repo, first_reply, calls
):
    from core.reviewers import ReviewerProcessError

    first = commit(repo, "a.py")
    commit(repo, "b.py")
    replies = [first_reply, findings_reply()]
    seen = []

    def runner(argv, cwd, stdin):
        seen.append(argv)
        reply = replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        if reply.startswith("process:"):
            raise ReviewerProcessError(reply.removeprefix("process:"))
        return reply

    manager = make_manager(repo, runner, config=FALLBACK_CONFIG)
    result = manager.await_result(manager.start(f"{first}..HEAD"), timeout=10)

    assert len(seen) == calls
    assert result["status"] == ("done" if calls == 2 else "failed")


@pytest.mark.parametrize(
    "stderr",
    [
        "pi exited 1 with no output: Disk quota exceeded",
        "pi exited 1 with no output: OSError: [Errno 122] Disk quota exceeded",
        "pi exited 1 with no output: [Errno 28] No space left on device",
        "pi exited 1 with no output: EACCES: permission denied, open '/x' (403)",
    ],
)
def test_a_local_failure_reported_by_the_reviewer_process_does_not_fall_back(
    repo, stderr
):
    from core.reviewers import ReviewerProcessError

    first = commit(repo, "a.py")
    commit(repo, "b.py")
    seen = []

    def runner(argv, cwd, stdin):
        seen.append(argv)
        raise ReviewerProcessError(stderr)

    manager = make_manager(repo, runner, config=FALLBACK_CONFIG)
    result = manager.await_result(manager.start(f"{first}..HEAD"), timeout=10)

    assert len(seen) == 1
    assert result["status"] == "failed"
