"""recreate-db.sh against a real pytest: whatever starts it (a shell
wrapper, pip's /bin/sh trampoline in a spaced venv path), the plugins
that pytest registers decide the default."""

import importlib.util
import sys
from pathlib import Path

import pytest

from core.adapter_contract import default_recreate_db_args
from tests.django_dist import django_dist

PYTEST_ADAPTER = str(
    Path(__file__).resolve().parents[1] / "adapters" / "pytest-adapter" / "run.sh"
)


def shell_wrapper(project):
    wrapper = project / ".venv" / "bin" / "pytest"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m pytest "$@"\n')
    wrapper.chmod(0o755)


def test_a_shell_wrapper_venv_pytest_is_asked_through_pytest_itself(
    tmp_path, monkeypatch
):
    """A /bin/sh wrapper that execs python -m pytest: only running the
    pytest run.sh would run tells which plugins it loads."""
    project = tmp_path / "project"
    shell_wrapper(project)
    monkeypatch.setenv("PYTHONPATH", str(django_dist(tmp_path / "site")))

    assert default_recreate_db_args(PYTEST_ADAPTER, str(project)) == "--create-db"


@pytest.mark.skipif(
    importlib.util.find_spec("pytest_django") is not None,
    reason="pytest-django is installed on the host",
)
def test_a_real_pytest_without_pytest_django_has_no_default(tmp_path, monkeypatch):
    project = tmp_path / "project"
    shell_wrapper(project)
    monkeypatch.delenv("PYTHONPATH", raising=False)

    assert default_recreate_db_args(PYTEST_ADAPTER, str(project)) is None


def test_a_pip_sh_trampoline_entry_point_in_a_spaced_venv_path_counts(
    tmp_path, monkeypatch
):
    """pip writes a /bin/sh trampoline instead of a plain #! line when the
    interpreter path has spaces or is too long for the kernel."""
    project = tmp_path / "my project"
    trampoline = project / ".venv" / "bin" / "pytest"
    trampoline.parent.mkdir(parents=True)
    trampoline.write_text(
        "#!/bin/sh\n"
        f"'''exec' \"{sys.executable}\" \"$0\" \"$@\"\n"
        "' '''\n"
        "import sys\n"
        "from pytest import console_main\n"
        "sys.exit(console_main())\n"
    )
    trampoline.chmod(0o755)
    monkeypatch.setenv("PYTHONPATH", str(django_dist(tmp_path / "site")))

    assert default_recreate_db_args(PYTEST_ADAPTER, str(project)) == "--create-db"
