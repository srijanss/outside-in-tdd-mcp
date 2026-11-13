"""The pytest adapter's recreate-db.sh asks the interpreter behind the
pytest that run.sh would actually execute — the project's .venv pytest,
or the PATH pytest when that one can't run — whether pytest_django is
importable."""

import os
import sys
from pathlib import Path

from core.adapter_contract import default_recreate_db_args

PYTEST_ADAPTER = str(
    Path(__file__).resolve().parents[1] / "adapters" / "pytest-adapter" / "run.sh"
)


def fake_pytest(path, interpreter, executable=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{interpreter}\nraise SystemExit(0)\n")
    path.chmod(0o755 if executable else 0o644)


def importable_django_plugin(root):
    package = root / "pytest_django"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    return str(root)


def path_pytest(tmp_path, monkeypatch, interpreter):
    bin_dir = tmp_path / "path-bin"
    fake_pytest(bin_dir / "pytest", interpreter)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_falls_back_to_the_path_pytest_when_the_venv_one_cannot_run(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    fake_pytest(project / ".venv" / "bin" / "pytest", "/nonexistent/python")
    path_pytest(tmp_path, monkeypatch, sys.executable)
    monkeypatch.setenv("PYTHONPATH", importable_django_plugin(tmp_path / "site"))

    assert default_recreate_db_args(PYTEST_ADAPTER, str(project)) == "--create-db"


def test_a_non_executable_venv_pytest_also_falls_back(tmp_path, monkeypatch):
    project = tmp_path / "project"
    fake_pytest(project / ".venv" / "bin" / "pytest", sys.executable, executable=False)
    path_pytest(tmp_path, monkeypatch, "/nonexistent/python")
    monkeypatch.setenv("PYTHONPATH", importable_django_plugin(tmp_path / "site"))

    assert default_recreate_db_args(PYTEST_ADAPTER, str(project)) is None


def test_asks_the_venv_pytests_own_interpreter(tmp_path, monkeypatch):
    project = tmp_path / "project"
    fake_pytest(project / ".venv" / "bin" / "pytest", sys.executable)
    monkeypatch.setenv("PYTHONPATH", importable_django_plugin(tmp_path / "site"))

    assert default_recreate_db_args(PYTEST_ADAPTER, str(project)) == "--create-db"
