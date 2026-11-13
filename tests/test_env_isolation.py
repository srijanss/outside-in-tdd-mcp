"""The test suite must not follow TDD_* paths inherited from the shell.

An orchestrated session exports e.g. TDD_FEATURES_PATH pointing at the main
checkout's real ledger. TDDServer honours that variable, so without
isolation every server a test builds on tmp_path would read and write the
real ledger instead of its own temp copy.
"""

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFTEST = ROOT / "tests" / "conftest.py"

INNER_TEST = textwrap.dedent(
    """
    from core.server import TDDServer

    def test_server_uses_its_own_ledger(tmp_path):
        server = TDDServer(str(tmp_path), str(tmp_path / ".tdd-config.json"))
        assert server.features_path == str(tmp_path / ".tdd-features.json")
        assert server.research_path == str(tmp_path / ".tdd-research.json")
    """
)


def test_inherited_tdd_env_does_not_reach_servers_built_in_tests(tmp_path):
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / "pytest.ini").write_text("[pytest]\n")
    if CONFTEST.exists():
        shutil.copy(CONFTEST, inner / "conftest.py")
    (inner / "test_inner.py").write_text(INNER_TEST)
    decoy = tmp_path / "real-ledger.json"
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "TDD_FEATURES_PATH": str(decoy),
        "TDD_RESEARCH_PATH": str(tmp_path / "real-research.json"),
    }

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-c", str(inner / "pytest.ini"), str(inner)],
        cwd=inner, env=env, capture_output=True, text=True, timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not decoy.exists()
