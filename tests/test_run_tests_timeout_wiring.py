import json

import pytest

import core.server as server_module
from core.adapter_contract import AdapterTimeoutError


@pytest.fixture
def server_with_timing_out_adapter(tmp_path, monkeypatch):
    seen = []

    def fake_run_adapter(adapter_path, target, project_root, timeout_s=None):
        seen.append(timeout_s)
        raise AdapterTimeoutError(f"Adapter timed out after {timeout_s}s", timeout_s)

    monkeypatch.setattr(server_module, "run_adapter", fake_run_adapter)
    adapter = tmp_path / "run.sh"
    adapter.write_text("#!/bin/sh\n")
    adapter.chmod(0o755)
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps(
            {
                "adapterPath": str(adapter),
                "adapterTimeoutSeconds": 60,
                "maxAdapterTimeoutSeconds": 300,
            }
        )
    )
    server = server_module.TDDServer(
        project_root=str(tmp_path), config_path=str(config_path)
    )
    server.call_tool(
        "init_feature",
        {"featureName": "t", "testFile": "tests/test_t.py", "targetFiles": []},
    )
    return server, seen


def run_tests(server, **arguments):
    return json.loads(server.call_tool("run_tests", arguments)[0].text)


def test_a_timeout_suggests_double_the_used_timeout(server_with_timing_out_adapter):
    server, seen = server_with_timing_out_adapter

    assert run_tests(server)["retryTimeoutSeconds"] == 120
    assert run_tests(server, timeoutSeconds=200)["retryTimeoutSeconds"] == 300
    assert seen == [60, 200]


def test_at_the_cap_there_is_no_retry_but_a_hint_and_above_it_nothing_runs(
    server_with_timing_out_adapter,
):
    server, seen = server_with_timing_out_adapter

    at_cap = run_tests(server, timeoutSeconds=300)
    assert "retryTimeoutSeconds" not in at_cap
    assert "maxAdapterTimeoutSeconds" in at_cap["hint"]

    above = run_tests(server, timeoutSeconds=301)
    assert "maxAdapterTimeoutSeconds" in above["error"]
    assert "retryTimeoutSeconds" not in above
    assert seen == [300]


def test_run_tests_advertises_timeout_seconds_and_retry_timeout_seconds():
    tool = next(t for t in server_module.TOOLS if t.name == "run_tests")

    assert tool.inputSchema["properties"]["timeoutSeconds"]["type"] == "integer"
    assert "retryTimeoutSeconds" in tool.description


def test_a_timeout_in_the_own_target_recheck_offers_a_retry_and_keeps_the_phase(
    tmp_path, monkeypatch
):
    from core.adapter_contract import AdapterResult

    seen = []
    replies = [
        AdapterResult(passed=1, failed=0),  # RED run: own target passes
        AdapterResult(  # closing sweep: something failed
            passed=0, failed=1, failures=[{"name": "t", "message": "m"}]
        ),
        None,  # own-target recheck: times out
    ]

    def fake_run_adapter(adapter_path, target, project_root, timeout_s=None):
        seen.append(timeout_s)
        reply = replies.pop(0)
        if reply is None:
            raise AdapterTimeoutError(
                f"Adapter timed out after {timeout_s}s", timeout_s
            )
        return reply

    monkeypatch.setattr(server_module, "run_adapter", fake_run_adapter)
    adapter = tmp_path / "run.sh"
    adapter.write_text("#!/bin/sh\n")
    adapter.chmod(0o755)
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps(
            {
                "adapterPath": str(adapter),
                "defaultTestDir": "tests/",
                "adapterTimeoutSeconds": 60,
                "maxAdapterTimeoutSeconds": 300,
            }
        )
    )
    server = server_module.TDDServer(
        project_root=str(tmp_path), config_path=str(config_path)
    )
    server.call_tool(
        "init_feature",
        {"featureName": "t", "testFile": "tests/test_t.py", "targetFiles": []},
    )
    run_tests(server)
    server.call_tool("verify", {})
    assert server.sm.phase == "refactor"

    result = run_tests(server, regressionScope="tests/", timeoutSeconds=100)

    assert seen == [60, 100, 100]
    assert result["retryTimeoutSeconds"] == 200
    assert server.sm.phase == "refactor"
