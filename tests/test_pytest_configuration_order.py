"""pytest applies repeated configuration overrides in order, the last one
winning, so the same overrides in another order are not known to be the
same configuration."""

from pathlib import Path

from core.adapter_contract import covers_full_suite

PYTEST_ADAPTER = str(
    Path(__file__).resolve().parents[1] / "adapters" / "pytest-adapter" / "run.sh"
)


def test_repeated_overrides_in_another_order_are_unknown(tmp_path):
    scope = "tests -o python_files=check_*.py -o python_files=test_*.py"
    suite = "tests -o python_files=test_*.py -o python_files=check_*.py"
    assert covers_full_suite(PYTEST_ADAPTER, str(tmp_path), scope, suite) is None
