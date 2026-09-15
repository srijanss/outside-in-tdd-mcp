import json

import pytest

from core.review_findings import list_review_findings, record_review_finding


def test_recording_a_finding_without_an_id_raises_a_clear_error(tmp_path):
    path = str(tmp_path / ".tdd-review-findings.json")

    with pytest.raises(ValueError, match="id"):
        record_review_finding("feature:checkout", {"status": "candidate"}, path=path)


def test_loading_malformed_json_raises_a_clear_error_instead_of_json_decode_error(tmp_path):
    path = tmp_path / ".tdd-review-findings.json"
    path.write_text("{not valid json")

    with pytest.raises(ValueError, match="Corrupt review findings file"):
        list_review_findings("feature:checkout", path=str(path))


def test_loading_an_invalid_stored_shape_raises_a_clear_error(tmp_path):
    path = tmp_path / ".tdd-review-findings.json"
    path.write_text('{"feature:checkout": "not-a-list"}')

    with pytest.raises(ValueError, match="must map scopes to lists of findings"):
        list_review_findings("feature:checkout", path=str(path))


def test_a_failed_write_does_not_corrupt_the_existing_file(tmp_path, monkeypatch):
    path = tmp_path / ".tdd-review-findings.json"
    record_review_finding("feature:checkout", {"id": "existing"}, path=str(path))
    original_content = path.read_text()

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(json, "dump", boom)

    with pytest.raises(RuntimeError):
        record_review_finding("feature:checkout", {"id": "new"}, path=str(path))

    assert path.read_text() == original_content


def test_recording_a_finding_as_fixed_removes_it_from_the_store(tmp_path):
    path = str(tmp_path / ".tdd-review-findings.json")
    record_review_finding(
        "feature:checkout",
        {"id": "missing-lock", "status": "candidate"},
        path=path,
    )

    record_review_finding(
        "feature:checkout",
        {"id": "missing-lock", "status": "fixed"},
        path=path,
    )

    assert list_review_findings("feature:checkout", path=path) == []


def test_recording_the_same_finding_id_replaces_it_within_a_shared_scope(tmp_path):
    path = str(tmp_path / ".tdd-review-findings.json")

    record_review_finding(
        "feature:checkout",
        {"id": "missing-lock", "status": "candidate"},
        path=path,
    )
    record_review_finding(
        "feature:checkout",
        {"id": "missing-lock", "status": "confirmed"},
        path=path,
    )

    assert list_review_findings("feature:checkout", path=path) == [
        {"id": "missing-lock", "status": "confirmed"}
    ]
