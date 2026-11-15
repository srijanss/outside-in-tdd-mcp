"""vitest scope.sh --covers-suite: output-only options don't narrow a run."""

from pathlib import Path

from core.adapter_contract import covers_full_suite

VITEST_ADAPTER = str(
    Path(__file__).resolve().parents[1] / "adapters" / "vitest-adapter" / "run.sh"
)


def covers(tmp_path, scope, suite):
    return covers_full_suite(VITEST_ADAPTER, str(tmp_path), scope, suite)


def test_output_only_flags_added_to_the_suite_still_cover_it(tmp_path):
    for scope in ("tests --reporter verbose", "--silent tests", "--reporter=dot tests"):
        assert covers(tmp_path, scope, "tests") is True, scope


def test_a_filter_narrows_and_an_unknown_option_is_unknown(tmp_path):
    assert covers(tmp_path, "-t smoke tests", "tests") is False
    assert covers(tmp_path, "tests/unit", "tests") is False
    assert covers(tmp_path, "tests", "tests/unit tests/e2e") is True
    assert covers(tmp_path, "", "tests") is True
    assert covers(tmp_path, "related src/a.ts", "tests") is False
    assert covers(tmp_path, "tests --some-new-flag", "tests") is None


def test_related_runs_compare_their_files_and_ignore_output_options(tmp_path):
    suite = "related src/a.ts"
    for scope in (
        "related src/a.ts --reporter verbose",
        "related --silent ./src/a.ts",
        "related src/a.ts src/b.ts",
    ):
        assert covers(tmp_path, scope, suite) is True, scope
    assert covers(tmp_path, "related src/b.ts", suite) is False
    assert covers(tmp_path, "related src/a.ts -t smoke", suite) is False
    assert covers(tmp_path, "tests", suite) is False
    assert covers(tmp_path, "related src/a.ts --some-new-flag", suite) is None
