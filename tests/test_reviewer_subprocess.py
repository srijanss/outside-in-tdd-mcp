from core.server import _run_reviewer_subprocess


def test_a_prompt_larger_than_the_per_argument_limit_reaches_the_reviewer_via_stdin(tmp_path):
    prompt = "x" * 1_000_000  # a single argv element this big fails with E2BIG

    output = _run_reviewer_subprocess(["cat"], str(tmp_path), prompt)

    assert output == prompt
