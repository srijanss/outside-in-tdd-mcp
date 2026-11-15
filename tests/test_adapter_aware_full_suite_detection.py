"""In changed mode, the adapter's own scope.sh --covers-suite answer decides
whether a regressionScope is the full suite: it knows which of its runner's
options only change output and which select tests.
"""

from pathlib import Path

from tests.test_changed_mode_withholds_full_suite import adapter_calls, sweep
from tests.test_regression_scope_from_changed_files import project

ADAPTERS = Path(__file__).resolve().parents[1] / "adapters"


def adapter_project(tmp_path, adapter, suite):
    return project(
        tmp_path,
        with_scope_script=True,
        scope_body=(ADAPTERS / adapter / "scope.sh").read_text(),
        extra_config={"regressionScopeDefault": "changed", "defaultTestDir": suite},
    )


def assert_refused(tmp_path, adapter, suite, scope):
    server = adapter_project(tmp_path, adapter, suite)
    before = adapter_calls(tmp_path)

    payload = sweep(server, scope)

    assert "gate" in payload.get("error", ""), scope
    assert adapter_calls(tmp_path) == before, scope


def test_pytest_output_only_flags_on_the_suite_are_refused(tmp_path):
    for name, scope in {"v": "tests/ -v", "tb": "tests --tb=short"}.items():
        assert_refused(tmp_path / name, "pytest-adapter", "tests/", scope)


def test_pytest_suite_targets_in_another_order_are_refused(tmp_path):
    assert_refused(
        tmp_path,
        "pytest-adapter",
        "-x ./tests ./integration",
        "-x ./integration ./tests",
    )


def test_cargo_output_only_flags_on_the_suite_are_refused(tmp_path):
    for name, scope in {
        "verbose": "--workspace --verbose",
        "nocapture": "--workspace -- --nocapture",
    }.items():
        assert_refused(tmp_path / name, "cargo-adapter", "--workspace", scope)


def test_vitest_output_only_flags_on_the_suite_are_refused(tmp_path):
    for name, scope in {
        "reporter": "tests --reporter verbose",
        "silent": "--silent tests",
    }.items():
        assert_refused(tmp_path / name, "vitest-adapter", "tests", scope)


def test_a_real_filter_on_the_suite_still_runs(tmp_path):
    for adapter, suite, scope in (
        ("pytest-adapter", "tests/", "tests -k smoke"),
        ("cargo-adapter", "--workspace", "-p crate"),
        ("vitest-adapter", "tests", "-t smoke tests"),
    ):
        server = adapter_project(tmp_path / adapter, adapter, suite)
        before = adapter_calls(tmp_path / adapter)

        payload = sweep(server, scope)

        assert "error" not in payload, (adapter, payload)
        assert len(adapter_calls(tmp_path / adapter)) > len(before), adapter
