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
    assert covers(tmp_path, "tests", "tests -k smoke") is True
    assert covers(tmp_path, "tests --some-plugin-flag", "tests") is None


def test_configuration_must_match_and_reordering_is_ignored(tmp_path):
    for scope, suite in (
        ("tests -p no:cacheprovider", "tests"),
        ("tests", "tests -p no:randomly"),
        ("tests -c other.ini", "tests"),
        ("tests -o python_files=*.py", "tests"),
        ("tests --rootdir sub", "tests"),
        ("tests --confcutdir sub", "tests"),
        ("tests --runxfail", "tests"),
        ("tests --strict-markers", "tests"),
    ):
        assert covers(tmp_path, scope, suite) is None, (scope, suite)
    assert covers(tmp_path, "tests -p no:x -o a=b", "tests -o a=b -p no:x") is True
    assert covers(tmp_path, "tests -p no:x -k smoke", "tests -p no:x") is False
    for scope in ("tests --ff", "tests --nf", "tests --new-first"):
        assert covers(tmp_path, scope, "tests") is True, scope


def test_configuration_order_matters(tmp_path):
    a, b = "-o python_files=a_*.py", "-o python_files=b_*.py"
    assert covers(tmp_path, f"tests {a} {b}", f"tests {b} {a}") is None
    assert covers(tmp_path, f"tests {a} -v {b}", f"tests {a} {b}") is True
    assert covers(tmp_path, f"tests -p x -p y", f"tests -p y -p x") is None
