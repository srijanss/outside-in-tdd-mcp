import json
import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = PROJECT_ROOT / "adapters" / "cargo-adapter" / "run.sh"
FIXTURE_PROJECT = PROJECT_ROOT / "tests" / "fixtures" / "cargo_project"
FAKE_CARGO_BIN = PROJECT_ROOT / "tests" / "fixtures" / "cargo_bin"


def run_adapter(test_target: str) -> dict:
    environment = {**os.environ, "PATH": f"{FAKE_CARGO_BIN}{os.pathsep}{os.environ.get('PATH', '')}"}
    proc = subprocess.run(
        [str(ADAPTER), test_target, str(FIXTURE_PROJECT)],
        capture_output=True,
        text=True,
        env=environment,
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
