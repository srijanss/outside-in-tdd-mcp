import json
from pathlib import Path

import pytest

from core.pi_events import PiReviewError, parse_pi_events

FIXTURES = Path(__file__).parent / "fixtures"


def ndjson(*events):
    return "\n".join(json.dumps(e) for e in events) + "\n"


def assistant(text, stop_reason="stop", **extra):
    return {
        "type": "message_end",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "stopReason": stop_reason,
            **extra,
        },
    }


SETTLED = {"type": "agent_settled", "aborted": False}


def test_a_settled_run_returns_the_final_assistant_text_from_a_real_capture():
    stream = (FIXTURES / "pi_success_events.jsonl").read_text()

    assert parse_pi_events(stream)["text"] == "ok"


@pytest.mark.parametrize(
    "stream, message",
    [
        (ndjson(assistant("partial")), "agent_settled"),
        (ndjson(assistant("partial"), {"type": "agent_settled", "aborted": True}), "aborted"),
        (
            ndjson(assistant("", "error", errorMessage="rate limited"), SETTLED),
            "rate limited",
        ),
        (ndjson(assistant("cut off", "length"), SETTLED), "length"),
        (ndjson({"type": "agent_start"}, SETTLED), "assistant"),
        ("", "agent_settled"),
    ],
)
def test_a_run_that_did_not_cleanly_finish_raises_instead_of_returning_text(stream, message):
    with pytest.raises(PiReviewError, match=message):
        parse_pi_events(stream)


def test_stray_non_json_lines_are_skipped_but_garbage_alone_still_fails():
    noisy = "Warning: something\n" + ndjson(assistant("fine"), SETTLED) + "\ntrailing junk\n"

    assert parse_pi_events(noisy)["text"] == "fine"
    with pytest.raises(PiReviewError, match="agent_settled"):
        parse_pi_events("Warning: something\nnot json at all\n")
