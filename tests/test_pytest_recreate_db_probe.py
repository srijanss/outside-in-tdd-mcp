"""The pytest adapter's recreate-db.sh asks the pytest that run.sh would
actually execute — the project's .venv pytest, or the PATH pytest when
that one can't be executed — for its registered plugins (`pytest -VV`).
The fakes here print canned `-VV` output, so nothing on the host leaks in."""

import os
import subprocess
import sys
from pathlib import Path

from core.adapter_contract import default_recreate_db_args
from tests.django_dist import django_dist

PYTEST_ADAPTER = str(
    Path(__file__).resolve().parents[1] / "adapters" / "pytest-adapter" / "run.sh"
)
DJANGO = "pytest-django-4.9.0"


def fake_pytest(path, plugins=(DJANGO,), interpreter="/bin/sh", executable=True):
    """A pytest whose -VV lists plugins (dist-version names)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(f'echo "  {plugin} at /site/{plugin}"\n' for plugin in plugins)
    path.write_text(
        f"#!{interpreter}\n"
        'echo "This is pytest version 9.1.1, imported from /site/pytest"\n'
        'echo "registered third-party plugins:"\n' + lines
    )
    path.chmod(0o755 if executable else 0o644)


def path_pytest(tmp_path, monkeypatch, **kwargs):
    bin_dir = tmp_path / "path-bin"
    fake_pytest(bin_dir / "pytest", **kwargs)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_a_venv_pytest_listing_pytest_django_defaults_to_create_db(tmp_path):
    fake_pytest(tmp_path / ".venv" / "bin" / "pytest")

    assert default_recreate_db_args(PYTEST_ADAPTER, str(tmp_path)) == "--create-db"


def test_a_venv_pytest_without_pytest_django_has_no_default(tmp_path, monkeypatch):
    fake_pytest(tmp_path / ".venv" / "bin" / "pytest", plugins=("pytest-xdist-3.6.1",))
    path_pytest(tmp_path, monkeypatch)  # must not be asked: the venv one runs

    assert default_recreate_db_args(PYTEST_ADAPTER, str(tmp_path)) is None


def test_falls_back_to_the_path_pytest_when_the_venv_one_cannot_run(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    fake_pytest(
        project / ".venv" / "bin" / "pytest", plugins=(), interpreter="/nonexistent/sh"
    )
    path_pytest(tmp_path, monkeypatch)  # only it lists pytest-django

    assert default_recreate_db_args(PYTEST_ADAPTER, str(project)) == "--create-db"


def test_a_non_executable_venv_pytest_also_falls_back(tmp_path, monkeypatch):
    project = tmp_path / "project"
    fake_pytest(project / ".venv" / "bin" / "pytest", plugins=(), executable=False)
    path_pytest(tmp_path, monkeypatch)

    assert default_recreate_db_args(PYTEST_ADAPTER, str(project)) == "--create-db"


def test_no_runnable_pytest_has_no_default(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))

    assert default_recreate_db_args(PYTEST_ADAPTER, str(tmp_path)) is None


def test_a_sh_trampoline_to_a_missing_interpreter_does_not_fall_back(
    tmp_path, monkeypatch
):
    """The trampoline itself starts (and exits 127), so run.sh stops there
    rather than trying the PATH pytest; the default must not come from the
    PATH pytest either."""
    project = tmp_path / "project"
    trampoline = project / ".venv" / "bin" / "pytest"
    trampoline.parent.mkdir(parents=True)
    trampoline.write_text(
        "#!/bin/sh\n"
        "'''exec' \"/nonexistent dir/python\" \"$0\" \"$@\"\n"
        "' '''\n"
    )
    trampoline.chmod(0o755)
    (project / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    bin_dir = tmp_path / "path-bin"
    bin_dir.mkdir()
    (bin_dir / "pytest").write_text(f'#!/bin/sh\nexec "{sys.executable}" -m pytest "$@"\n')
    (bin_dir / "pytest").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PYTHONPATH", str(django_dist(tmp_path / "site")))

    ran = subprocess.run(
        [PYTEST_ADAPTER, "test_ok.py", str(project)], capture_output=True, text=True
    )
    assert (ran.returncode, ran.stdout) == (1, "")  # no fallback: no report
    assert default_recreate_db_args(PYTEST_ADAPTER, str(project)) is None
