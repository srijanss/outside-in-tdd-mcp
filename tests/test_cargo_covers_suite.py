"""cargo scope.sh --covers-suite: output-only options don't narrow a run."""

from pathlib import Path

from core.adapter_contract import covers_full_suite

CARGO_ADAPTER = str(
    Path(__file__).resolve().parents[1] / "adapters" / "cargo-adapter" / "run.sh"
)


def covers(tmp_path, scope, suite):
    return covers_full_suite(CARGO_ADAPTER, str(tmp_path), scope, suite)


def test_output_only_flags_added_to_the_suite_still_cover_it(tmp_path):
    for scope in (
        "--workspace --verbose",
        "--workspace -- --nocapture",
        "-q --workspace --color never -- --test-threads 1 --show-output",
    ):
        assert covers(tmp_path, scope, "--workspace") is True, scope


def test_a_filter_narrows_and_an_unknown_option_is_unknown(tmp_path):
    assert covers(tmp_path, "-p crate", "--workspace") is False
    assert covers(tmp_path, "--workspace smoke", "--workspace") is False
    assert covers(tmp_path, "--workspace -- --skip slow", "--workspace") is False
    assert covers(tmp_path, "--workspace", "--workspace -p crate") is True
    assert covers(tmp_path, "-p b -p a", "--package a -p b") is True
    assert covers(tmp_path, "--workspace --some-new-flag", "--workspace") is None
