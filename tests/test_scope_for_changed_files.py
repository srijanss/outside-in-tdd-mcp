from core.adapter_contract import NOTHING_TO_RUN, scope_for_changed_files


def adapter_with_scope(tmp_path, scope_body):
    run = tmp_path / "run.sh"
    run.write_text("#!/bin/sh\n")
    run.chmod(0o755)
    if scope_body is not None:
        scope = tmp_path / "scope.sh"
        scope.write_text(scope_body)
        scope.chmod(0o755)
    return str(run)


def test_the_sibling_scope_script_maps_changed_files_to_a_scope(tmp_path):
    adapter = adapter_with_scope(
        tmp_path,
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "print(json.dumps({'scope': sys.argv[1] + '|' + ' '.join(sys.argv[2:])}))\n",
    )

    assert (
        scope_for_changed_files(adapter, "/root", ["a.py", "b c.py"])
        == "/root|a.py b c.py"
    )


def test_the_mode_reaches_the_scope_script_through_its_environment(tmp_path):
    adapter = adapter_with_scope(
        tmp_path,
        "#!/usr/bin/env python3\n"
        "import json, os\n"
        "print(json.dumps({'scope': os.environ.get('TDD_SCOPE_MODE', 'unset')}))\n",
    )

    assert scope_for_changed_files(adapter, "/r", ["a"], mode="changed") == "changed"
    assert scope_for_changed_files(adapter, "/r", ["a"]) == "unset"


def test_no_mode_drops_a_scope_mode_inherited_from_the_server(tmp_path, monkeypatch):
    monkeypatch.setenv("TDD_SCOPE_MODE", "changed")
    adapter = adapter_with_scope(
        tmp_path,
        "#!/usr/bin/env python3\n"
        "import json, os\n"
        "print(json.dumps({'scope': os.environ.get('TDD_SCOPE_MODE', 'unset')}))\n",
    )

    assert scope_for_changed_files(adapter, "/r", ["a"]) == "unset"


def test_an_empty_scope_is_told_apart_from_no_mapping(tmp_path):
    empty = adapter_with_scope(
        tmp_path, "#!/bin/sh\necho '{\"scope\": null, \"empty\": true}'\n"
    )

    assert scope_for_changed_files(empty, "/r", ["a"]) == NOTHING_TO_RUN
    assert NOTHING_TO_RUN is not None


def test_no_mapping_when_the_script_is_missing_fails_or_declines(tmp_path):
    assert scope_for_changed_files(adapter_with_scope(tmp_path, None), "/r", ["a"]) is None
    for body in (
        "#!/bin/sh\nexit 1\n",
        "#!/bin/sh\necho not-json\n",
        "#!/bin/sh\necho '{\"scope\": null}'\n",
        "#!/bin/sh\necho '{\"scope\": \"  \"}'\n",
        "#!/bin/sh\necho '[1]'\n",
    ):
        adapter = adapter_with_scope(tmp_path, body)
        assert scope_for_changed_files(adapter, "/r", ["a"]) is None, body


def test_no_mapping_without_changed_files_or_when_the_script_hangs(tmp_path):
    adapter = adapter_with_scope(tmp_path, "#!/bin/sh\necho '{\"scope\": \"x\"}'\n")
    assert scope_for_changed_files(adapter, "/r", []) is None

    hanging = adapter_with_scope(tmp_path, "#!/bin/sh\nexec sleep 30\n")
    assert scope_for_changed_files(hanging, "/r", ["a"], timeout_s=1) is None


def test_no_mapping_when_the_script_prints_invalid_utf8(tmp_path):
    adapter = adapter_with_scope(tmp_path, "#!/bin/sh\nprintf '\\377\\376'\n")
    assert scope_for_changed_files(adapter, "/r", ["a"]) is None


def test_a_timeout_also_kills_a_child_the_scope_script_spawned(tmp_path):
    import time

    from tests.test_adapter_timeout_config import _is_gone

    pid_file = tmp_path / "child.pid"
    # No exec: the sleep is a child that inherits the stdout pipe.
    adapter = adapter_with_scope(
        tmp_path, f"#!/bin/sh\nsleep 30 &\necho $! > {pid_file}\nwait\n"
    )

    started = time.monotonic()
    assert scope_for_changed_files(adapter, "/r", ["a"], timeout_s=1) is None
    assert time.monotonic() - started < 10

    child = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while not _is_gone(child) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert _is_gone(child)
