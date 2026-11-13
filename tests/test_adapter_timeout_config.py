import json
import shutil
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


def _process_group_of(pid):
    # Field 5 of /proc/<pid>/stat; split after the comm field, which may hold spaces.
    with open(f"/proc/{pid}/stat") as f:
        return int(f.read().split(") ", 1)[1].split()[2])


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


def test_timeout_returns_even_when_a_child_escaped_the_process_group(tmp_path):
    import os
    import signal

    adapter = tmp_path / "escaping-adapter.sh"
    pid_file = tmp_path / "escaped.pid"
    # setsid moves the child into its own session, out of reach of the
    # group kill, while it still holds the inherited stdout pipe.
    adapter.write_text(
        f"#!/bin/sh\nsetsid sleep 30 &\necho $! > {pid_file}\nwait\n"
    )
    adapter.chmod(0o755)
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps({"adapterPath": str(adapter), "adapterTimeoutSeconds": 1})
    )
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))
    server.call_tool(
        "init_feature",
        {"featureName": "esc", "testFile": "tests/test_esc.py", "targetFiles": []},
    )

    # Without setsid the child would stay in the group and the test would
    # pass without exercising the escape at all.
    assert shutil.which("setsid"), "setsid is required for this test"

    started = time.monotonic()
    try:
        result = run_tests(server)
        elapsed = time.monotonic() - started
        escaped = int(pid_file.read_text())
        # The child really left the adapter's group and outlived the kill,
        # so it was still holding the pipe when run_tests returned.
        assert not _is_gone(escaped)
        assert _process_group_of(escaped) == escaped
    finally:
        try:
            os.kill(int(pid_file.read_text()), signal.SIGKILL)
        except (FileNotFoundError, ValueError, ProcessLookupError):
            pass

    assert elapsed < 10
    assert "timed out after 1s" in result["error"]
