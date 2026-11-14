from core.server import _run_reviewer_subprocess


def test_a_prompt_larger_than_the_per_argument_limit_reaches_the_reviewer_via_stdin(tmp_path):
    prompt = "x" * 1_000_000  # a single argv element this big fails with E2BIG

    output = _run_reviewer_subprocess(["cat"], str(tmp_path), prompt)

    assert output == prompt


def test_a_reviewer_that_prints_nothing_raises_a_reviewer_process_error(tmp_path):
    import pytest

    from core.reviewers import ReviewerProcessError

    argv = ["sh", "-c", "echo 'Error: 429 quota exceeded' >&2; exit 1"]
    with pytest.raises(ReviewerProcessError, match="exited 1 with no output: Error: 429"):
        _run_reviewer_subprocess(argv, str(tmp_path), "prompt")
