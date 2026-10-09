import json

import pytest

from core.claude_output import ClaudeReviewError, parse_claude_output


def result(**overrides):
    return json.dumps({
        "type": "result", "subtype": "success", "is_error": False,
        "terminal_reason": "completed", "result": "the answer", **overrides,
    })


def test_a_successful_result_yields_its_text():
    assert parse_claude_output(result()) == {"text": "the answer"}


@pytest.mark.parametrize("output, message", [
    ("", "no output"),
    ("not json", "not valid JSON"),
    ("[1]", "unexpected output"),
    (result(is_error=True, result="Credit balance too low"), "Credit balance too low"),
    (result(subtype="error_max_turns"), "error_max_turns"),
    (result(terminal_reason="max_tokens"), "max_tokens"),
    (json.dumps({"type": "system"}), "unexpected output"),
    (result(result=None), "no result text"),
])
def test_anything_but_a_clean_completed_result_is_an_error(output, message):
    with pytest.raises(ClaudeReviewError, match=message):
        parse_claude_output(output)
