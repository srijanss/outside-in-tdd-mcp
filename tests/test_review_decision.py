from core.review_decision import decide


def finding(id="f", severity="high", status="open", **extra):
    return {"id": id, "severity": severity, "status": status, **extra}


def test_done_when_no_open_medium_or_higher_findings_remain():
    findings = [
        finding("nit", severity="low"),
        finding("handled", status="rejected", reason="intended"),
        finding("later", status="deferred", reason="out of scope"),
    ]

    assert decide(1, findings)["decision"] == "done"
    assert decide(1, [])["decision"] == "done"


def test_continue_while_a_medium_or_higher_finding_is_open_under_the_round_cap():
    assert decide(1, [finding(severity="medium")])["decision"] == "continue"
    assert decide(2, [finding(severity="critical")])["decision"] == "continue"


def test_escalate_when_the_round_cap_is_hit_with_blocking_findings_still_open():
    result = decide(3, [finding(severity="high")])

    assert result["decision"] == "escalate"
    assert "3 rounds" in result["reason"]
    assert decide(3, [finding(severity="low")])["decision"] == "done"


def test_escalate_when_a_blocking_finding_rejected_twice_comes_back():
    comeback = finding("again", severity="medium", rejectedCount=2)

    result = decide(1, [comeback])

    assert result["decision"] == "escalate"
    assert "again" in result["reason"]
    assert decide(1, [finding("once", rejectedCount=1)])["decision"] == "continue"
