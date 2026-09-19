"""Console-script entry points for the language-specific test adapters.

Lets `pip install -e .` (or a real install) put `pytest-adapter-runner` /
`vitest-adapter-runner` on PATH as stable, project-independent executables
— any project's .tdd-config.json can then set `adapterPath` to that name
(resolved via PATH lookup) instead of needing Docker or an absolute path
back into this repo's checkout. ADAPTERS_DIR resolves relative to this
file's own installed location, so it stays correct for an editable install
even if the checkout moves.
"""
import subprocess
import sys
from pathlib import Path

ADAPTERS_DIR = Path(__file__).resolve().parent.parent / "adapters"


def _run(adapter_dir_name: str) -> int:
    script = ADAPTERS_DIR / adapter_dir_name / "run.sh"
    return subprocess.call([str(script), *sys.argv[1:]])


def cargo_adapter_main() -> None:
    sys.exit(_run("cargo-adapter"))


def pytest_adapter_main() -> None:
    sys.exit(_run("pytest-adapter"))


def vitest_adapter_main() -> None:
    sys.exit(_run("vitest-adapter"))
