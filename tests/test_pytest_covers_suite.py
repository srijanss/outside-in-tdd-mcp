"""pytest scope.sh --covers-suite: output-only options don't narrow a run."""

from pathlib import Path

from core.adapter_contract import covers_full_suite

PYTEST_ADAPTER = str(
    Path(__file__).resolve().parents[1] / "adapters" / "pytest-adapter" / "run.sh"
)


def covers(tmp_path, scope, suite):
    return covers_full_suite(PYTEST_ADAPTER, str(tmp_path), scope, suite)


def test_output_only_flags_added_to_the_suite_still_cover_it(tmp_path):
    for scope in ("tests -v", "tests/ --tb=short", "-q --tb short ./tests"):
        assert covers(tmp_path, scope, "tests/") is True, scope


def test_a_filter_narrows_and_an_unknown_option_is_unknown(tmp_path):
    assert covers(tmp_path, "tests -k smoke", "tests") is False
    assert covers(tmp_path, "tests -p no:cacheprovider", "tests") is False
    assert covers(tmp_path, "tests", "tests -k smoke") is True
    assert covers(tmp_path, "tests --some-plugin-flag", "tests") is None
