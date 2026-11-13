"""A real interpreter isolated from this test run's environment, for tests
whose outcome must not depend on what happens to be installed here."""

import subprocess
import sys
from pathlib import Path


def isolated_python(root: Path) -> Path:
    """Create a venv at root without system site-packages or pip, and
    return its python."""
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(root)], check=True
    )
    return root / "bin" / "python"
