import json

import pytest

from core.review_findings_parser import FindingsParseError, parse_findings

FINDING = {
    "id": "missing-lock",
    "severity": "high",
    "file": "core/server.py",
    "line": 42,
    "claim": "Concurrent writes can lose findings",
    "suggestion": "Take the findings lock around the read-modify-write",
}


def fenced(payload):
    return "Here is my review.\n\n```json\n" + json.dumps(payload) + "\n```\n\nDone."


def test_extracts_findings_from_a_fenced_json_block_surrounded_by_prose():
    text = fenced({"findings": [FINDING]})

    assert parse_findings(text) == [FINDING]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Looks good to me, no issues found.",
        "```json\n{not valid json\n```",
        '```json\n{"issues": []}\n```',
        '```json\n{"findings": "none"}\n```',
    ],
)
def test_output_without_a_valid_findings_payload_raises_instead_of_returning_empty(text):
    with pytest.raises(FindingsParseError):
        parse_findings(text)


@pytest.mark.parametrize(
    "mutation, field",
    [
        ({"id": None}, "id"),
        ({"severity": "urgent"}, "severity"),
        ({"file": ""}, "file"),
        ({"line": "42"}, "line"),
        ({"claim": None}, "claim"),
        ({"suggestion": None}, "suggestion"),
    ],
)
def test_a_finding_violating_the_schema_raises_naming_the_field(mutation, field):
    bad = {**FINDING, **mutation}
    bad = {k: v for k, v in bad.items() if v is not None}

    with pytest.raises(FindingsParseError, match=field):
        parse_findings(fenced({"findings": [FINDING, bad]}))


def test_the_last_json_block_wins_when_the_reviewer_emits_several():
    draft = fenced({"findings": [{**FINDING, "id": "draft"}]})
    final = fenced({"findings": [FINDING]})

    assert parse_findings(draft + "\n\nOn reflection:\n\n" + final) == [FINDING]


def test_an_explicit_empty_findings_list_is_a_valid_clean_review():
    assert parse_findings(fenced({"findings": []})) == []
