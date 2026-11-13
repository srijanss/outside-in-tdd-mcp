import json
import time

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


def run_tests(server):
    return json.loads(server.call_tool("run_tests", {})[0].text)


def test_config_adapter_timeout_seconds_bounds_the_run_and_keeps_the_phase(tmp_path):
    server = server_with_sleeping_adapter(tmp_path, adapterTimeoutSeconds=1)

    started = time.monotonic()
    result = run_tests(server)

    assert time.monotonic() - started < 10
    assert "timed out after 1s" in result["error"]
    assert server.sm.phase == "red"


def _is_gone(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(") ", 1)[1].startswith("Z")
    except FileNotFoundError:
        return True


def test_timeout_also_kills_a_child_the_adapter_spawned_without_exec(tmp_path):
    adapter = tmp_path / "forking-adapter.sh"
    pid_file = tmp_path / "child.pid"
    # No exec: the sleep is a child that inherits the stdout pipe.
    adapter.write_text(f"#!/bin/sh\nsleep 30 &\necho $! > {pid_file}\nwait\n")
    adapter.chmod(0o755)
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps({"adapterPath": str(adapter), "adapterTimeoutSeconds": 1})
    )
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))
    server.call_tool(
        "init_feature",
        {"featureName": "fork", "testFile": "tests/test_fork.py", "targetFiles": []},
    )

    started = time.monotonic()
    result = run_tests(server)

    assert time.monotonic() - started < 10
    assert "timed out after 1s" in result["error"]
    child = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while not _is_gone(child) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert _is_gone(child)
