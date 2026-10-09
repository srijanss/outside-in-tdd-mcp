BLOCKING_SEVERITIES = ("medium", "high", "critical")
MAX_ROUNDS = 3


def decide(round_number: int, findings: list[dict]) -> dict:
    blocking = [
        f
        for f in findings
        if f.get("status") == "open" and f.get("severity") in BLOCKING_SEVERITIES
    ]
    if not blocking:
        return {"decision": "done"}
    persistent = [f for f in blocking if f.get("rejectedCount", 0) >= 2]
    if persistent:
        ids = ", ".join(f["id"] for f in persistent)
        return {
            "decision": "escalate",
            "reason": f"finding(s) rejected twice came back: {ids}",
        }
    if round_number >= MAX_ROUNDS:
        return {
            "decision": "escalate",
            "reason": f"{MAX_ROUNDS} rounds done and blocking findings are still open",
        }
    return {"decision": "continue"}
