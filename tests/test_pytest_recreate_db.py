import os
import sys
from pathlib import Path

from core.adapter_contract import default_recreate_db_args
from tests.isolated_python import isolated_python

REPO = Path(__file__).resolve().parents[1]
PYTEST_ADAPTER = str(REPO / "adapters" / "pytest-adapter" / "run.sh")


def venv_pytest(root, interpreter=sys.executable):
    """A project .venv whose pytest runs on interpreter (by default this
    test run's)."""
    pytest = root / ".venv" / "bin" / "pytest"
    pytest.parent.mkdir(parents=True, exist_ok=True)
    pytest.write_text(f"#!{interpreter}\nraise SystemExit(0)\n")
    pytest.chmod(0o755)


def test_a_project_venv_with_pytest_django_defaults_to_create_db(
    tmp_path, monkeypatch
):
    venv_pytest(tmp_path / "project")
    (tmp_path / "site" / "pytest_django").mkdir(parents=True)
    (tmp_path / "site" / "pytest_django" / "__init__.py").write_text("")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "site"))

    args = default_recreate_db_args(PYTEST_ADAPTER, str(tmp_path / "project"))

    assert args == "--create-db"


def test_a_project_venv_without_pytest_django_has_no_default(tmp_path, monkeypatch):
    # Not this run's interpreter: a pytest-django installed on the host
    # must not leak into the "without" case.
    venv_pytest(tmp_path, isolated_python(tmp_path / ".venv"))
    monkeypatch.delenv("PYTHONPATH", raising=False)

    assert default_recreate_db_args(PYTEST_ADAPTER, str(tmp_path)) is None


def test_the_recreate_db_script_ships_with_the_package_and_image():
    pyproject = (REPO / "pyproject.toml").read_text()
    dockerfile = (REPO / "Dockerfile").read_text()

    assert '"*/*.sh"' in pyproject
    assert "/adapters/pytest-adapter/recreate-db.sh" in dockerfile


def test_a_venv_pytest_that_starts_but_cannot_reach_python_is_not_skipped(
    tmp_path, monkeypatch
):
    """pip's /bin/sh trampoline starts even when the python it execs is
    gone, so like run.sh the helper must not move on to the PATH pytest."""
    pytest = tmp_path / ".venv" / "bin" / "pytest"
    pytest.parent.mkdir(parents=True)
    pytest.write_text(
        "#!/bin/sh\n'\'\'exec' \"/nonexistent dir/python\" \"$0\" \"$@\"\n' \'\'\'\n"
    )
    pytest.chmod(0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "pytest").write_text(f"#!{sys.executable}\nraise SystemExit(0)\n")
    (bin_dir / "pytest").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    (tmp_path / "site" / "pytest_django").mkdir(parents=True)
    (tmp_path / "site" / "pytest_django" / "__init__.py").write_text("")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "site"))

    assert default_recreate_db_args(PYTEST_ADAPTER, str(tmp_path)) is None
