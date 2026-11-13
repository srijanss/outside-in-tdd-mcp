"""recreate-db.sh against real interpreters and a real venv: no project
venv (PATH pytest), and a venv whose pytest-django is reachable only
through a .pth, as with an editable install — a directory scan of
site-packages would miss it."""

import os
import subprocess
import sys
from pathlib import Path

from core.adapter_contract import default_recreate_db_args

PYTEST_ADAPTER = str(
    Path(__file__).resolve().parents[1] / "adapters" / "pytest-adapter" / "run.sh"
)


def plugin_dir(root):
    (root / "pytest_django").mkdir(parents=True)
    (root / "pytest_django" / "__init__.py").write_text("")
    return root


def pytest_script(path, interpreter):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{interpreter}\nraise SystemExit(0)\n")
    path.chmod(0o755)


def real_venv(root, *flags):
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", *flags, str(root)],
        check=True,
    )
    python = root / "bin" / "python"
    pytest_script(root / "bin" / "pytest", python)
    purelib = subprocess.run(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return Path(purelib)


def test_without_a_project_venv_the_path_pytests_interpreter_decides(
    tmp_path, monkeypatch
):
    bin_dir = tmp_path / "bin"
    pytest_script(bin_dir / "pytest", sys.executable)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    project = tmp_path / "project"
    project.mkdir()

    monkeypatch.setenv("PYTHONPATH", str(plugin_dir(tmp_path / "site")))
    assert default_recreate_db_args(PYTEST_ADAPTER, str(project)) == "--create-db"

    monkeypatch.delenv("PYTHONPATH")
    assert default_recreate_db_args(PYTEST_ADAPTER, str(project)) is None


def test_an_editable_install_in_a_real_project_venv_counts(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    project = tmp_path / "project"
    site = real_venv(project / ".venv")
    assert default_recreate_db_args(PYTEST_ADAPTER, str(project)) is None

    (site / "editable.pth").write_text(f"{plugin_dir(tmp_path / 'src')}\n")

    assert default_recreate_db_args(PYTEST_ADAPTER, str(project)) == "--create-db"


def test_a_pip_sh_trampoline_entry_point_in_a_spaced_venv_path_counts(
    tmp_path, monkeypatch
):
    """pip writes a /bin/sh trampoline instead of a plain #! line when the
    interpreter path has spaces or is too long for the kernel."""
    monkeypatch.delenv("PYTHONPATH", raising=False)
    project = tmp_path / "my project"
    site = real_venv(project / ".venv")
    python = project / ".venv" / "bin" / "python"
    (project / ".venv" / "bin" / "pytest").write_text(
        "#!/bin/sh\n"
        f"'''exec' \"{python}\" \"$0\" \"$@\"\n"
        "' '''\n"
        "raise SystemExit(0)\n"
    )
    (site / "editable.pth").write_text(f"{plugin_dir(tmp_path / 'src')}\n")

    assert default_recreate_db_args(PYTEST_ADAPTER, str(project)) == "--create-db"

