import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core.adapter_contract import AdapterError, AdapterResult, run_adapter


def test_run_adapter_default_timeout_is_configurable_via_env_var(tmp_path, monkeypatch):
    # The 120s default in run_adapter()'s signature is too short for some
    # projects' full suites. Rather than hardcoding it, the default should
    # be overridable per project — via TDD_ADAPTER_TIMEOUT_S, set in the
    # project's .mcp.json env block (same mechanism already used there for
    # TDD_PROJECT_ROOT/TDD_CONFIG_PATH/PATH) — without callers needing to
    # pass timeout_s explicitly.
    slow_adapter = tmp_path / "slow_adapter.sh"
    slow_adapter.write_text("#!/bin/sh\nsleep 2\necho '{\"passed\": 1, \"failed\": 0}'\n")
    slow_adapter.chmod(slow_adapter.stat().st_mode | stat.S_IEXEC)

    monkeypatch.setenv("TDD_ADAPTER_TIMEOUT_S", "1")

    with pytest.raises(AdapterError, match="timed out after 1s"):
        run_adapter(str(slow_adapter), "irrelevant", str(tmp_path))


def test_run_adapter_raises_clean_error_for_non_integer_timeout_env_var(tmp_path, monkeypatch):
    # int(os.environ["TDD_ADAPTER_TIMEOUT_S"]) previously raised an
    # unhandled ValueError for a malformed value (e.g. "abc"), crashing the
    # whole MCP tool call instead of surfacing a clear, catchable
    # AdapterError like every other failure mode in this function.
    adapter = tmp_path / "adapter.sh"
    adapter.write_text("#!/bin/sh\necho '{\"passed\": 1, \"failed\": 0}'\n")
    adapter.chmod(adapter.stat().st_mode | stat.S_IEXEC)

    monkeypatch.setenv("TDD_ADAPTER_TIMEOUT_S", "abc")

    with pytest.raises(AdapterError, match="TDD_ADAPTER_TIMEOUT_S"):
        run_adapter(str(adapter), "irrelevant", str(tmp_path))


@pytest.mark.parametrize("value", ["0", "-5"])
def test_run_adapter_treats_zero_or_negative_timeout_env_var_as_immediate_timeout(
    tmp_path, monkeypatch, value
):
    # A zero or negative TDD_ADAPTER_TIMEOUT_S is a clearly-misconfigured
    # value, not a crash: int() parses it fine, and subprocess.run raises
    # TimeoutExpired (not ValueError) for a non-positive timeout, which
    # run_adapter already catches into a clean AdapterError. Pin that
    # behavior down explicitly rather than leaving it implied.
    adapter = tmp_path / "adapter.sh"
    adapter.write_text("#!/bin/sh\nsleep 0.2\necho '{\"passed\": 1, \"failed\": 0}'\n")
    adapter.chmod(adapter.stat().st_mode | stat.S_IEXEC)

    monkeypatch.setenv("TDD_ADAPTER_TIMEOUT_S", value)

    with pytest.raises(AdapterError, match="timed out"):
        run_adapter(str(adapter), "irrelevant", str(tmp_path))


def test_from_json_rejects_negative_passed():
    with pytest.raises(AdapterError):
        AdapterResult.from_json({"passed": -1, "failed": 0})


def test_from_json_rejects_negative_failed():
    with pytest.raises(AdapterError):
        AdapterResult.from_json({"passed": 0, "failed": -1})


def test_from_json_rejects_negative_duration_ms():
    with pytest.raises(AdapterError):
        AdapterResult.from_json({"passed": 0, "failed": 0, "duration_ms": -5})


@pytest.mark.parametrize(
    "data",
    [
        5,  # not a JSON object
        {"passed": "not a number", "failed": 0},
        {"passed": "3", "failed": 0},  # numeric string
        {"passed": 1.5, "failed": 0},
        {"passed": True, "failed": 0},
        {"passed": 0, "failed": None},
        {"passed": 0, "failed": 1, "failures": None},
        {"passed": 0, "failed": 1, "failures": [{"name": 1, "message": "m"}]},
        {"passed": 0, "failed": 0, "duration_ms": "fast"},
    ],
)
def test_from_json_rejects_malformed_output_with_adapter_error(data):
    # Anything but a clean AdapterError escapes the server's adapter error
    # handling as a raw ValueError/TypeError.
    with pytest.raises(AdapterError):
        AdapterResult.from_json(data)
