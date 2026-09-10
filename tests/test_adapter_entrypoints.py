import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core import adapter_entrypoints


def test_pytest_adapter_main_execs_the_pytest_adapter_script(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pytest-adapter-runner", "tests/", "/some/project"])

    with patch("core.adapter_entrypoints.subprocess.call", return_value=0) as mock_call:
        with pytest.raises(SystemExit) as exc_info:
            adapter_entrypoints.pytest_adapter_main()

    mock_call.assert_called_once_with(
        [
            str(adapter_entrypoints.ADAPTERS_DIR / "pytest-adapter" / "run.sh"),
            "tests/",
            "/some/project",
        ]
    )
    assert exc_info.value.code == 0


def test_vitest_adapter_main_execs_the_vitest_adapter_script(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["vitest-adapter-runner", "src/", "/some/project"])

    with patch("core.adapter_entrypoints.subprocess.call", return_value=1) as mock_call:
        with pytest.raises(SystemExit) as exc_info:
            adapter_entrypoints.vitest_adapter_main()

    mock_call.assert_called_once_with(
        [
            str(adapter_entrypoints.ADAPTERS_DIR / "vitest-adapter" / "run.sh"),
            "src/",
            "/some/project",
        ]
    )
    assert exc_info.value.code == 1


def test_adapters_dir_resolves_to_the_real_adapters_directory():
    assert adapter_entrypoints.ADAPTERS_DIR.name == "adapters"
    assert (adapter_entrypoints.ADAPTERS_DIR / "pytest-adapter" / "run.sh").exists()
    assert (adapter_entrypoints.ADAPTERS_DIR / "vitest-adapter" / "run.sh").exists()
