import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = PROJECT_ROOT / "adapters" / "cargo-adapter" / "run.sh"
FIXTURE_PROJECT = PROJECT_ROOT / "tests" / "fixtures" / "cargo_project"
FAKE_CARGO_BIN = PROJECT_ROOT / "tests" / "fixtures" / "cargo_bin"
FAKE_CARGO_HOME = PROJECT_ROOT / "tests" / "fixtures" / "cargo_home"


def run_adapter(test_target: str, environment: dict | None = None) -> dict:
    adapter_environment = {
        **os.environ,
        "PATH": f"{FAKE_CARGO_BIN}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    if environment is not None:
        adapter_environment.update(environment)
    proc = subprocess.run(
        [sys.executable, str(ADAPTER), test_target, str(FIXTURE_PROJECT)],
        capture_output=True,
        text=True,
        env=adapter_environment,
    )
    return json.loads(proc.stdout)


def test_adapter_reports_passing_cargo_tests():
    result = run_adapter("passing")

    assert result["passed"] == 1
    assert result["failed"] == 0
    assert result["failures"] == []
    assert result["duration_ms"] >= 0


def test_adapter_reports_failing_cargo_tests():
    result = run_adapter("failing")

    assert result["passed"] == 0
    assert result["failed"] == 1
    assert len(result["failures"]) == 1
    assert result["failures"][0]["name"] == "tests::failing"
    assert "assertion" in result["failures"][0]["message"]


def test_adapter_finds_cargo_in_the_standard_rust_home_when_path_omits_it():
    result = run_adapter(
        "passing",
        {"PATH": "", "HOME": str(FAKE_CARGO_HOME)},
    )

    assert result["passed"] == 1
    assert result["failed"] == 0
