import pytest

from core.review_rounds import list_rounds, record_round


def test_rounds_are_numbered_sequentially_per_scope_and_listed_in_order(tmp_path):
    path = str(tmp_path / ".tdd-review-rounds.json")

    first = record_round("review:aaa", {"head": "h1", "findings": []}, path=path)
    second = record_round("review:aaa", {"head": "h2", "findings": []}, path=path)
    other = record_round("review:bbb", {"head": "h9", "findings": []}, path=path)

    assert (first["round"], second["round"], other["round"]) == (1, 2, 1)
    assert [r["head"] for r in list_rounds("review:aaa", path=path)] == ["h1", "h2"]
    assert [r["head"] for r in list_rounds("review:bbb", path=path)] == ["h9"]
    assert list_rounds("review:none", path=path) == []
    assert "recordedAt" in first


@pytest.mark.parametrize("content", ["{not json", '["a list"]', '{"review:a": "not-a-list"}'])
def test_a_corrupt_rounds_file_raises_a_clear_error_and_is_left_untouched(tmp_path, content):
    path = tmp_path / ".tdd-review-rounds.json"
    path.write_text(content)

    with pytest.raises(ValueError, match="Corrupt review rounds file"):
        list_rounds("review:a", path=str(path))
    with pytest.raises(ValueError, match="Corrupt review rounds file"):
        record_round("review:a", {"head": "h"}, path=str(path))

    assert path.read_text() == content
