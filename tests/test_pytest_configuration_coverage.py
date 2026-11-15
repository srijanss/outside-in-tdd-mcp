"""pytest options that change configuration (-p, -c, -o, --rootdir,
--confcutdir) can enable tests as well as hide them, so --covers-suite
can't say a scope that differs in them runs fewer tests: it answers
unknown and leaves the decision to the core check."""

from pathlib import Path

from core.adapter_contract import covers_full_suite

PYTEST_ADAPTER = str(
    Path(__file__).resolve().parents[1] / "adapters" / "pytest-adapter" / "run.sh"
)


def test_a_configuration_change_is_unknown_rather_than_a_filter(tmp_path):
    assert (
        covers_full_suite(
            PYTEST_ADAPTER, str(tmp_path), "tests -p no:cacheprovider", "tests"
        )
        is None
    )
