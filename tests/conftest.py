import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_tdd_env(monkeypatch):
    """Drop TDD_* variables inherited from the shell for every test.

    TDDServer resolves its ledger/research/state/log paths from TDD_* env vars
    before falling back to project_root. An orchestrated session exports e.g.
    TDD_FEATURES_PATH pointing at the main checkout's real ledger, so without
    this every server a test builds on tmp_path would write that real file.
    A test that needs one sets it itself with monkeypatch.setenv.
    """
    for name in [n for n in os.environ if n.startswith("TDD_")]:
        monkeypatch.delenv(name)
