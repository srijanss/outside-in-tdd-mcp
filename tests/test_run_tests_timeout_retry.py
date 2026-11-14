import json

from core.server import TDDServer


def server_with_sleeping_adapter(tmp_path, **config):
    adapter = tmp_path / "slow-adapter.sh"
    adapter.write_text("#!/bin/sh\nexec sleep 30\n")
    adapter.chmod(0o755)
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(json.dumps({"adapterPath": str(adapter), **config}))
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))
    server.call_tool(
        "init_feature",
        {"featureName": "slow", "testFile": "tests/test_slow.py", "targetFiles": []},
    )
    return server


def run_tests(server, **arguments):
    return json.loads(server.call_tool("run_tests", arguments)[0].text)


def test_a_per_call_timeout_overrides_config_and_a_timeout_offers_a_doubled_retry(
    tmp_path,
):
    server = server_with_sleeping_adapter(
        tmp_path, adapterTimeoutSeconds=60, maxAdapterTimeoutSeconds=600
    )

    result = run_tests(server, timeoutSeconds=1)

    assert "timed out after 1s" in result["error"]
    assert result["retryTimeoutSeconds"] == 2
    assert server.sm.phase == "red"
