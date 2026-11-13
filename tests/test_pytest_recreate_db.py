from pathlib import Path

from core.adapter_contract import default_recreate_db_args

REPO = Path(__file__).resolve().parents[1]
PYTEST_ADAPTER = str(REPO / "adapters" / "pytest-adapter" / "run.sh")


def venv(root, *packages):
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "pytest").write_text("")
    site = root / ".venv" / "lib" / "python3.11" / "site-packages"
    site.mkdir(parents=True)
    for package in packages:
        (site / package).mkdir()


def test_a_project_venv_with_pytest_django_defaults_to_create_db(tmp_path):
    venv(tmp_path, "pytest_django")

    assert default_recreate_db_args(PYTEST_ADAPTER, str(tmp_path)) == "--create-db"


def test_a_project_venv_without_pytest_django_has_no_default(tmp_path):
    venv(tmp_path)

    assert default_recreate_db_args(PYTEST_ADAPTER, str(tmp_path)) is None


def test_the_recreate_db_script_ships_with_the_package_and_image():
    pyproject = (REPO / "pyproject.toml").read_text()
    dockerfile = (REPO / "Dockerfile").read_text()

    assert '"*/*.sh"' in pyproject
    assert "/adapters/pytest-adapter/recreate-db.sh" in dockerfile
