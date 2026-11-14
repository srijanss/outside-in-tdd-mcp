"""Packaging of the pytest adapter's recreate-db.sh; its behaviour is
covered by test_pytest_recreate_db_probe.py (canned pytests) and
test_pytest_recreate_db_real_envs.py (a real pytest)."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_the_recreate_db_script_ships_with_the_package_and_image():
    pyproject = (REPO / "pyproject.toml").read_text()
    dockerfile = (REPO / "Dockerfile").read_text()

    assert '"*/*.sh"' in pyproject
    assert "/adapters/pytest-adapter/recreate-db.sh" in dockerfile
