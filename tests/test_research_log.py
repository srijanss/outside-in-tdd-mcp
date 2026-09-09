import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core.research_log import list_research, record_research


def test_record_research_appends_multiple_entries_in_order(tmp_path):
    path = str(tmp_path / ".tdd-research.json")

    record_research(source="https://a.example", summary="first", path=path)
    record_research(source="https://b.example", summary="second", path=path)
    record_research(source="https://c.example", summary="third", path=path)

    entries = list_research(path=path)

    assert [e["source"] for e in entries] == [
        "https://a.example",
        "https://b.example",
        "https://c.example",
    ]


def test_record_research_stores_related_feature_when_given(tmp_path):
    path = str(tmp_path / ".tdd-research.json")

    record_research(
        source="https://example.com",
        summary="informed a decision",
        related_feature="research-log",
        path=path,
    )

    entries = list_research(path=path)

    assert entries[0]["relatedFeature"] == "research-log"


def test_list_research_returns_empty_when_file_contains_corrupted_json(tmp_path):
    path = tmp_path / ".tdd-research.json"
    path.write_text("{not valid json")

    entries = list_research(path=str(path))

    assert entries == []


def test_list_research_returns_empty_when_file_contains_non_list_json(tmp_path):
    path = tmp_path / ".tdd-research.json"
    path.write_text(json.dumps({"not": "a list"}))

    entries = list_research(path=str(path))

    assert entries == []


def test_record_research_then_list_research_returns_entry(tmp_path):
    path = str(tmp_path / ".tdd-research.json")

    record_research(
        source="https://x.com/sairahul1/status/2063544956158185927",
        summary="Harness engineering: agent = model + harness.",
        path=path,
    )

    entries = list_research(path=path)

    assert len(entries) == 1
    assert entries[0]["source"] == "https://x.com/sairahul1/status/2063544956158185927"
    assert entries[0]["summary"] == "Harness engineering: agent = model + harness."
    assert entries[0]["relatedFeature"] is None
    assert "date" in entries[0]
