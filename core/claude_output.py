import json


class ClaudeReviewError(Exception):
    pass


def parse_claude_output(stdout: str) -> dict:
    """The review text from `claude -p --output-format json`. Only a clean,
    completed, non-error result counts; the exit code is not trusted."""
    if not stdout.strip():
        raise ClaudeReviewError("claude produced no output")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ClaudeReviewError(f"claude output is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("type") != "result":
        raise ClaudeReviewError("claude returned unexpected output")
    if data.get("is_error"):
        raise ClaudeReviewError(f"claude reported an error: {data.get('result')}")
    if data.get("subtype") != "success":
        raise ClaudeReviewError(f"claude did not succeed: {data.get('subtype')}")
    if data.get("terminal_reason") != "completed":
        raise ClaudeReviewError(
            f"claude stopped early: {data.get('terminal_reason')}"
        )
    if not isinstance(data.get("result"), str):
        raise ClaudeReviewError("claude returned no result text")
    return {"text": data["result"]}
