import json


class PiReviewError(RuntimeError):
    pass


def _load_events(stream: str) -> list[dict]:
    events = []
    for line in stream.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and "type" in event:
            events.append(event)
    return events


def parse_pi_events(stream: str) -> dict:
    events = _load_events(stream)

    settled = [e for e in events if e["type"] == "agent_settled"]
    if not settled:
        raise PiReviewError("pi run never reached agent_settled")
    if settled[-1].get("aborted"):
        raise PiReviewError("pi run was aborted")

    assistant = [
        e["message"]
        for e in events
        if e["type"] == "message_end" and e["message"]["role"] == "assistant"
    ]
    if not assistant:
        raise PiReviewError("pi run produced no assistant message")

    final = assistant[-1]
    if final.get("stopReason") != "stop":
        detail = final.get("errorMessage") or final.get("stopReason")
        raise PiReviewError(f"pi assistant message did not finish cleanly: {detail}")

    text = "".join(
        part["text"] for part in final["content"] if part["type"] == "text"
    )
    return {"text": text}
