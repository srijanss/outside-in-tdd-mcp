import json
import time

from core.server import TDDServer


def server_with_sleeping_adapter(tmp_path, **config):
    adapter = tmp_path / "slow-adapter.sh"
    # exec so the killed process is the sleep itself — no grandchild keeps
    # the stdout pipe open past the timeout.
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


def run_tests(server):
    return json.loads(server.call_tool("run_tests", {})[0].text)


def test_config_adapter_timeout_seconds_bounds_the_run_and_keeps_the_phase(tmp_path):
    server = server_with_sleeping_adapter(tmp_path, adapterTimeoutSeconds=1)

    started = time.monotonic()
    result = run_tests(server)

    assert time.monotonic() - started < 10
    assert "timed out after 1s" in result["error"]
    assert server.sm.phase == "red"
