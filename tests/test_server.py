import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core.server import TDDServer

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_server(tmp_path):
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps(
            {
                "adapterPath": str(
                    PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh"
                )
            }
        )
    )
    return TDDServer(project_root=str(tmp_path), config_path=str(config_path))


def call(server, name, **arguments):
    result = server.call_tool(name, arguments)
    return json.loads(result[0].text)


def test_unknown_tool_returns_error_without_raising(tmp_path):
    server = make_server(tmp_path)
    payload = call(server, "not_a_real_tool")
    assert payload == {"error": "Unknown tool: not_a_real_tool"}


def test_missing_required_argument_returns_clear_error(tmp_path):
    server = make_server(tmp_path)
    payload = call(server, "init_feature", featureName="f")  # missing testFile
    assert payload["error"] == "Missing required argument: 'testFile'"


def test_missing_target_files_argument_returns_clear_error(tmp_path):
    server = make_server(tmp_path)
    payload = call(server, "init_feature", featureName="f", testFile="t.py")
    assert payload["error"] == "Missing required argument: 'targetFiles'"


def test_init_feature_returns_clear_error_for_invalid_target_files(tmp_path):
    server = make_server(tmp_path)

    payload = call(
        server, "init_feature", featureName="f", testFile="t.py", targetFiles="f.py"
    )
    assert "target_files must be a list or tuple of strings" in payload["error"]

    payload = call(
        server, "init_feature", featureName="f", testFile="t.py", targetFiles=[1, 2]
    )
    assert "target_files must be a list of strings" in payload["error"]

    # a valid call still works after the rejected ones
    payload = call(
        server, "init_feature", featureName="f", testFile="t.py", targetFiles=["f.py"]
    )
    assert payload["phase"] == "red"


def test_drill_down_returns_clear_error_for_invalid_target_files(tmp_path):
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        '#!/usr/bin/env python3\n'
        'import json\n'
        'print(json.dumps({"passed": 0, "failed": 1, "failures": []}))\n'
    )
    fake_adapter.chmod(0o755)
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(json.dumps({"adapterPath": str(fake_adapter)}))
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))

    call(server, "init_feature", featureName="f", testFile="t.py", targetFiles=["f.py"])
    call(server, "run_tests")  # -> verify_red
    call(server, "verify")  # -> implement

    payload = call(server, "drill_down", testFile="sub.py", targetFiles="not_a_list.py")
    assert "target_files must be a list or tuple of strings" in payload["error"]

    payload = call(server, "drill_down", testFile="sub.py", targetFiles=[None])
    assert "target_files must be a list of strings" in payload["error"]

    # a valid call still works after the rejected ones
    payload = call(server, "drill_down", testFile="sub.py", targetFiles=["sub_impl.py"])
    assert payload["ok"] is True
    assert payload["depth"] == 2


def test_drill_down_missing_target_files_argument_returns_clear_error(tmp_path):
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        '#!/usr/bin/env python3\n'
        'import json\n'
        'print(json.dumps({"passed": 0, "failed": 1, "failures": []}))\n'
    )
    fake_adapter.chmod(0o755)
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(json.dumps({"adapterPath": str(fake_adapter)}))
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))

    call(server, "init_feature", featureName="f", testFile="t.py", targetFiles=["f.py"])
    call(server, "run_tests")  # -> verify_red
    call(server, "verify")  # -> implement

    payload = call(server, "drill_down", testFile="sub.py")  # missing targetFiles
    assert payload["error"] == "Missing required argument: 'targetFiles'"


def test_phase_error_returns_clear_error_without_raising(tmp_path):
    server = make_server(tmp_path)
    call(server, "init_feature", featureName="f", testFile="tests/test_x.py", targetFiles=["tests/test_x.py"])
    payload = call(server, "write_code", filePath="f.py")
    assert "only allowed in IMPLEMENT phase" in payload["error"]


def test_write_code_blocked_for_file_outside_declared_targets(tmp_path):
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        '#!/usr/bin/env python3\n'
        'import json\n'
        'print(json.dumps({"passed": 0, "failed": 1, "failures": []}))\n'
    )
    fake_adapter.chmod(0o755)
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(json.dumps({"adapterPath": str(fake_adapter)}))
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))

    call(server, "init_feature", featureName="f", testFile="t.py", targetFiles=["views.py"])
    call(server, "run_tests")  # failed=1 -> verify_red
    call(server, "verify")  # -> implement

    payload = call(server, "write_code", filePath="new_module.py")

    assert "declared target files" in payload["error"]
    assert call(server, "write_code", filePath="views.py") == {"ok": True}


def test_get_status_reports_target_files(tmp_path):
    server = make_server(tmp_path)
    call(
        server,
        "init_feature",
        featureName="f",
        testFile="tests/test_x.py",
        targetFiles=["views.py", "urls.py"],
    )

    status = call(server, "get_status")

    assert status["targetFiles"] == ["views.py", "urls.py"]
    assert status["stack"][0]["targetFiles"] == ["views.py", "urls.py"]


def test_get_status_reports_target_files_at_nested_depth(tmp_path):
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        '#!/usr/bin/env python3\n'
        'import json\n'
        'print(json.dumps({"passed": 0, "failed": 1, "failures": []}))\n'
    )
    fake_adapter.chmod(0o755)
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(json.dumps({"adapterPath": str(fake_adapter)}))
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))

    call(
        server,
        "init_feature",
        featureName="f",
        testFile="tests/test_x.py",
        targetFiles=["views.py"],
    )
    call(server, "run_tests")  # -> verify_red
    call(server, "verify")  # -> implement
    call(
        server,
        "drill_down",
        testFile="cart/tests.py",
        targetFiles=["cart/models.py", "cart/urls.py"],
    )

    status = call(server, "get_status")

    assert status["targetFiles"] == ["cart/models.py", "cart/urls.py"]
    assert status["stack"][0]["targetFiles"] == ["views.py"]
    assert status["stack"][1]["targetFiles"] == ["cart/models.py", "cart/urls.py"]


def test_no_active_feature_returns_clear_error_without_raising(tmp_path):
    server = make_server(tmp_path)
    payload = call(server, "write_test", testName="t")
    assert payload["error"] == "No active feature. Call init_feature() first."


def test_phase_gate_only_tools_return_minimal_ack(tmp_path):
    # write_test/write_test_skeleton/write_code/refactor_code never mutate
    # phase/depth/testFile/cycleCount — echoing the full status back on
    # every one of these (the most frequently-called tools in the
    # workflow) would just resend state the caller already has.
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        '''#!/usr/bin/env python3
import json, pathlib, sys
counter_file = pathlib.Path(__file__).parent / "count.txt"
count = int(counter_file.read_text()) if counter_file.exists() else 0
count += 1
counter_file.write_text(str(count))
if count == 1:
    print(json.dumps({"passed": 0, "failed": 1, "failures": []}))
else:
    print(json.dumps({"passed": 1, "failed": 0, "failures": []}))
'''
    )
    fake_adapter.chmod(0o755)
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(json.dumps({"adapterPath": str(fake_adapter)}))
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))

    call(server, "init_feature", featureName="f", testFile="t.py", targetFiles=["f.py"])
    assert call(server, "write_test", testName="t") == {"ok": True}
    assert call(server, "write_test_skeleton", testName="t") == {"ok": True}

    call(server, "run_tests")  # failed=1 -> verify_red
    call(server, "verify")  # -> implement
    assert call(server, "write_code", filePath="f.py") == {"ok": True}

    call(server, "run_tests")  # passed=1 -> verify_green
    call(server, "verify")  # -> refactor
    assert call(server, "refactor_code", description="tidy up") == {"ok": True}


def test_init_feature_returns_status_via_call_tool(tmp_path):
    server = make_server(tmp_path)
    payload = call(server, "init_feature", featureName="f", testFile="tests/test_x.py", targetFiles=["tests/test_x.py"])
    assert payload["featureName"] == "f"
    assert payload["testFile"] == "tests/test_x.py"
    assert payload["phase"] == "red"


def test_init_feature_appends_session_log_entry(tmp_path):
    server = make_server(tmp_path)
    call(server, "init_feature", featureName="f", testFile="tests/test_x.py", targetFiles=["tests/test_x.py"])

    log_path = tmp_path / ".tdd-session.log"
    assert log_path.exists()
    entry = json.loads(log_path.read_text().strip().splitlines()[-1])
    assert entry["event"] == "init_feature"
    assert entry["featureName"] == "f"
    assert entry["testFile"] == "tests/test_x.py"
    assert entry["phase"] == "red"
    assert "ts" in entry


def test_session_log_records_lifecycle_events(tmp_path):
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        '''#!/usr/bin/env python3
import json, pathlib, sys
counter_file = pathlib.Path(__file__).parent / "count.txt"
count = int(counter_file.read_text()) if counter_file.exists() else 0
count += 1
counter_file.write_text(str(count))
if count == 1:
    print(json.dumps({"passed": 0, "failed": 1, "failures": []}))
else:
    print(json.dumps({"passed": 1, "failed": 0, "failures": []}))
'''
    )
    fake_adapter.chmod(0o755)
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(json.dumps({"adapterPath": str(fake_adapter)}))
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))

    call(server, "init_feature", featureName="f", testFile="t.py", targetFiles=["f.py"])
    call(server, "write_test", testName="t")
    call(server, "run_tests")  # failed=1 -> verify_red
    call(server, "verify")  # -> implement
    call(server, "write_code", filePath="f.py")

    call(server, "drill_down", testFile="subA.py", targetFiles=["subA_impl.py"])
    call(server, "abandon_drill_down")  # unneeded, back to implement

    call(server, "drill_down", testFile="subB.py", targetFiles=["subB_impl.py"])
    call(server, "write_test", testName="sub")
    call(server, "run_tests")  # passed=1, nested red -> verify_green (skip)
    call(server, "verify")  # -> refactor (nested)
    call(server, "refactor_code", description="nested tidy up")
    call(server, "run_tests")  # passed=1 -> nested back to red, cycle 1
    call(server, "return_to_parent")  # -> back to implement at base

    call(server, "run_tests")  # passed=1 -> verify_green
    call(server, "verify")  # -> refactor
    call(server, "refactor_code", description="tidy up")
    call(server, "run_tests")  # passed=1 -> red, cycle 1
    call(server, "complete_feature")

    call(server, "init_feature", featureName="g", testFile="g.py", targetFiles=["g.py"])
    call(server, "reset_feature")

    log_path = tmp_path / ".tdd-session.log"
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    events = [e["event"] for e in entries]
    assert events == [
        "init_feature",
        "write_test",
        "run_tests",
        "verify",
        "write_code",
        "drill_down",
        "abandon_drill_down",
        "drill_down",
        "write_test",
        "run_tests",
        "verify",
        "refactor_code",
        "run_tests",
        "return_to_parent",
        "run_tests",
        "verify",
        "refactor_code",
        "run_tests",
        "complete_feature",
        "init_feature",
        "reset_feature",
    ]

    complete_entry = entries[events.index("complete_feature")]
    assert complete_entry["featureName"] == "f"
    assert complete_entry["testFile"] == "t.py"
    assert complete_entry["cyclesCompleted"] == 1
    # phase/depth reflect the state machine's post-completion state (fully
    # cleared), not the completed feature's last phase — that's always
    # RED/depth-1 by complete_feature()'s own gate, so it carries no
    # information worth logging.
    assert complete_entry["phase"] is None
    assert complete_entry["depth"] == 0

    reset_entry = entries[-1]
    assert reset_entry["featureName"] == "g"
    assert reset_entry["testFile"] == "g.py"
    assert reset_entry["phase"] is None
    assert reset_entry["depth"] == 0

    # Cycle-count fields must be named consistently across level-scoped
    # completion events (return_to_parent, complete_feature) and the
    # unconditional abandon_drill_down, so log consumers don't have to
    # special-case one event's field name.
    abandon_entry = entries[events.index("abandon_drill_down")]
    assert abandon_entry["cyclesCompleted"] == 0
    return_entry = entries[events.index("return_to_parent")]
    assert return_entry["cyclesCompleted"] == 1


def test_write_test_skeleton_appends_session_log_entry(tmp_path):
    server = make_server(tmp_path)
    call(server, "init_feature", featureName="f", testFile="tests/test_x.py", targetFiles=["tests/test_x.py"])

    call(server, "write_test_skeleton", testName="t")

    log_path = tmp_path / ".tdd-session.log"
    entry = json.loads(log_path.read_text().strip().splitlines()[-1])
    assert entry["event"] == "write_test_skeleton"
    assert entry["testName"] == "t"


def test_log_event_does_not_raise_on_non_serializable_field(tmp_path):
    server = make_server(tmp_path)
    call(server, "init_feature", featureName="f", testFile="tests/test_x.py", targetFiles=["tests/test_x.py"])

    server._log_event("custom_event", bad=object())  # must not raise

    log_path = tmp_path / ".tdd-session.log"
    lines = log_path.read_text().strip().splitlines()
    last_entry = json.loads(lines[-1])
    assert last_entry["event"] in ("init_feature", "custom_event")


def test_log_event_swallows_oserror_when_log_path_unwritable(tmp_path):
    server = make_server(tmp_path)
    call(server, "init_feature", featureName="f", testFile="tests/test_x.py", targetFiles=["tests/test_x.py"])
    # Parent directory doesn't exist -> open(..., "a") raises OSError.
    server.session_log_path = str(tmp_path / "no-such-dir" / "session.log")

    payload = call(server, "write_test", testName="t")  # must not raise

    assert payload == {"ok": True}
    assert not (tmp_path / "no-such-dir").exists()


def test_run_tests_appends_session_log_entry_with_result(tmp_path):
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps(
            {
                "adapterPath": str(
                    PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh"
                )
            }
        )
    )
    server = TDDServer(
        project_root=str(PROJECT_ROOT),
        config_path=str(config_path),
    )
    server.session_log_path = str(tmp_path / ".tdd-session.log")
    call(server, "init_feature", featureName="f", testFile="tests/test_state_machine.py", targetFiles=["tests/test_state_machine.py"])

    call(server, "run_tests")

    log_path = tmp_path / ".tdd-session.log"
    entry = json.loads(log_path.read_text().strip().splitlines()[-1])
    assert entry["event"] == "run_tests"
    assert entry["passed"] > 0
    assert entry["failed"] == 0
    assert entry["phase"] == "verify_green"
    assert isinstance(entry["durationMs"], int)


def test_run_tests_uses_active_test_file_not_default_test_dir(tmp_path):
    # defaultTestDir is only ever consulted when no test_file is set on the
    # state machine — but call_tool's run_tests always has an active
    # feature (checked via self.sm.phase is None first). Point
    # defaultTestDir at a fixture that would fail, and the actual test
    # target at one that passes, to prove defaultTestDir has zero effect
    # while a feature is active.
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps(
            {
                "adapterPath": str(
                    PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh"
                ),
                "defaultTestDir": "tests/fixtures/broken_import_module.py",
            }
        )
    )
    server = TDDServer(project_root=str(PROJECT_ROOT), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="tests/test_state_machine.py", targetFiles=["tests/test_state_machine.py"])

    payload = call(server, "run_tests")

    assert payload["testResult"]["failed"] == 0
    assert payload["testResult"]["passed"] > 0


def test_init_feature_returns_clear_error_when_adapter_path_does_not_exist(tmp_path):
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps({"adapterPath": str(tmp_path / "no-such-adapter.sh")})
    )
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))

    payload = call(server, "init_feature", featureName="f", testFile="tests/test_x.py", targetFiles=["tests/test_x.py"])

    assert "no-such-adapter.sh" in payload["error"]
    # init_feature must not have gone through — a bad adapterPath should be
    # caught before any feature state is created.
    status = call(server, "get_status")
    assert status["featureName"] is None


def test_refactor_closing_cycle_also_checks_full_suite_for_regressions(tmp_path):
    # A base-level feature whose own target already passes, but where the
    # configured defaultTestDir (the "whole suite") is currently broken.
    # Closing the REFACTOR cycle must not advance back to RED / bump
    # cycle_count while something else is broken — otherwise
    # complete_feature() becomes reachable on top of a regression.
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps(
            {
                "adapterPath": str(
                    PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh"
                ),
                "defaultTestDir": "tests/fixtures/broken_import_module.py",
            }
        )
    )
    server = TDDServer(project_root=str(PROJECT_ROOT), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="tests/test_state_machine.py", targetFiles=["tests/test_state_machine.py"])

    # test_state_machine.py already passes -> red skips straight to verify_green
    payload = call(server, "run_tests")
    assert payload["phase"] == "verify_green"
    call(server, "verify")  # -> refactor

    payload = call(server, "run_tests")

    assert payload["phase"] == "refactor"
    assert payload["cycleCount"] == 0
    assert payload["testResult"]["failed"] >= 1


def test_regression_check_merges_passed_counts_and_reports_accurate_error(tmp_path):
    adapter_path = str(PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh")
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps(
            {
                "adapterPath": adapter_path,
                "defaultTestDir": "tests/fixtures/mixed_pass_and_fail.py",
            }
        )
    )
    server = TDDServer(project_root=str(PROJECT_ROOT), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="tests/test_state_machine.py", targetFiles=["tests/test_state_machine.py"])

    own_result = json.loads(
        subprocess.run(
            [adapter_path, "tests/test_state_machine.py", str(PROJECT_ROOT)],
            capture_output=True,
            text=True,
        ).stdout
    )

    call(server, "run_tests")  # red -> verify_green (own target already passes)
    call(server, "verify")  # -> refactor

    payload = call(server, "run_tests")  # closes refactor -> triggers regression check

    assert payload["phase"] == "refactor"  # blocked: regression found
    # The regression fixture has 1 passing and 1 failing test — both must
    # be counted, not just the failure.
    assert payload["testResult"]["passed"] == own_result["passed"] + 1
    assert payload["testResult"]["failed"] == 1
    # A regression elsewhere didn't come from this refactor — the error
    # message must not blame the refactor for it.
    assert "Refactor broke the tests" not in (payload["lastError"] or "")


def test_regression_check_does_not_double_count_overlapping_tests(tmp_path):
    # defaultTestDir overlapping test_target (the common, realistic case)
    # must not sum two separate adapter runs — that double-counts the
    # overlap. Uses an isolated tmp_path suite (never the live tests/ dir)
    # so this doesn't recursively invoke the currently-running test suite.
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "test_a.py").write_text(
        "def test_a1():\n    assert True\n\n\ndef test_a2():\n    assert True\n"
    )
    (suite_dir / "test_b.py").write_text("def test_b1():\n    assert True\n")

    adapter_path = str(PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh")
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps({"adapterPath": adapter_path, "defaultTestDir": "."})
    )
    server = TDDServer(project_root=str(suite_dir), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="test_a.py", targetFiles=["test_a.py"])

    whole_suite = json.loads(
        subprocess.run(
            [adapter_path, ".", str(suite_dir)], capture_output=True, text=True
        ).stdout
    )
    assert whole_suite["passed"] == 3  # sanity: 2 in test_a.py + 1 in test_b.py

    call(server, "run_tests")  # red -> verify_green (own target already passes)
    call(server, "verify")  # -> refactor

    payload = call(server, "run_tests")  # closes refactor -> regression check runs

    assert payload["phase"] == "red"  # nothing actually broken -> cycle closes
    assert payload["cycleCount"] == 1
    assert payload["testResult"]["passed"] == 3  # not 5 (2 own + 3 whole, double-counted)
    assert payload["testResult"]["failed"] == 0


def test_regression_check_handles_default_test_dir_with_space(tmp_path):
    # defaultTestDir follows the same contract as test_target: it's parsed
    # as a full pytest argument expression, not treated as one opaque path.
    # So a literal directory name containing a space must be quoted by the
    # caller in the config value itself (matching run.sh's own documented
    # shlex-split contract) — an unquoted "dir with space" would otherwise
    # be parsed as three separate (nonexistent) targets.
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "test_a.py").write_text("def test_a1():\n    assert True\n")
    spaced_dir = suite_dir / "dir with space"
    spaced_dir.mkdir()
    (spaced_dir / "test_b.py").write_text("def test_b1():\n    assert True\n")

    adapter_path = str(PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh")
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps({"adapterPath": adapter_path, "defaultTestDir": '"dir with space"'})
    )
    server = TDDServer(project_root=str(suite_dir), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="test_a.py", targetFiles=["test_a.py"])

    call(server, "run_tests")  # red -> verify_green (own target already passes)
    call(server, "verify")  # -> refactor

    payload = call(server, "run_tests")  # closes refactor -> regression check runs

    assert payload["phase"] == "red"  # nothing actually broken -> cycle closes
    assert payload["cycleCount"] == 1
    assert payload["testResult"]["passed"] == 2  # test_a.py + test_b.py
    assert payload["testResult"]["failed"] == 0


def test_regression_check_supports_defaulttestdir_with_extra_pytest_args(tmp_path):
    # defaultTestDir isn't always a bare path — run.sh's own contract says
    # the combined target can be "a full pytest argument expression" (e.g.
    # ". --ignore=vendor"). shlex.quote()-ing the whole defaultTestDir value
    # as one token breaks that: "." and "--ignore=vendor" collapse into a
    # single literal (nonexistent) path "'. --ignore=vendor'" instead of two
    # pytest args, so pytest immediately errors with "collected 0 items"
    # instead of running the regression sweep. The regression run must
    # preserve multiple space-separated args in defaultTestDir.
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "test_a.py").write_text("def test_a1():\n    assert True\n")
    vendor_dir = suite_dir / "vendor"
    vendor_dir.mkdir()
    (vendor_dir / "test_vendor.py").write_text("def test_v1():\n    assert False\n")

    adapter_path = str(PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh")
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps({"adapterPath": adapter_path, "defaultTestDir": ". --ignore=vendor"})
    )
    server = TDDServer(project_root=str(suite_dir), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="test_a.py", targetFiles=["test_a.py"])

    call(server, "run_tests")  # red -> verify_green (own target already passes)
    call(server, "verify")  # -> refactor

    payload = call(server, "run_tests")  # closes refactor -> regression check runs

    assert payload["phase"] == "red"  # vendor/ ignored, nothing actually broke
    assert payload["cycleCount"] == 1
    assert payload["testResult"]["passed"] == 1  # test_a.py only
    assert payload["testResult"]["failed"] == 0


def test_regression_check_skips_when_default_test_dir_is_whitespace_only(tmp_path):
    # A whitespace-only defaultTestDir (e.g. "   ") is truthy in Python, so
    # it used to pass closing_base_refactor's truthiness check and trigger
    # a regression run — but shlex.split() collapses pure whitespace to
    # nothing, silently degrading run_target back to just test_target. The
    # regression check would then report success having actually checked
    # nothing beyond the cycle's own test. Treat it the same as an unset
    # defaultTestDir: skip the regression check entirely instead of running
    # a no-op that looks like real coverage.
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "test_a.py").write_text("def test_a1():\n    assert True\n")
    vendor_dir = suite_dir / "vendor"
    vendor_dir.mkdir()
    (vendor_dir / "test_vendor.py").write_text("def test_v1():\n    assert False\n")

    adapter_path = str(PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh")
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps({"adapterPath": adapter_path, "defaultTestDir": "   "})
    )
    server = TDDServer(project_root=str(suite_dir), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="test_a.py", targetFiles=["test_a.py"])

    call(server, "run_tests")  # red -> verify_green (own target already passes)
    call(server, "verify")  # -> refactor

    payload = call(server, "run_tests")  # closes refactor; regression check must be skipped

    assert payload["phase"] == "red"
    assert payload["cycleCount"] == 1
    assert payload["testResult"]["passed"] == 1  # test_a.py only — no phantom regression run
    assert payload["testResult"]["failed"] == 0


def test_regression_check_reports_clean_error_for_malformed_default_test_dir(tmp_path):
    # An unbalanced quote in defaultTestDir (e.g. a config typo) makes
    # run.sh's shlex.split() raise ValueError, crashing the adapter script
    # with a raw Python traceback on stderr instead of running anything.
    # The server should catch this itself and surface a clear config error
    # instead of forwarding a confusing traceback dump.
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "test_a.py").write_text("def test_a1():\n    assert True\n")

    adapter_path = str(PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh")
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps({"adapterPath": adapter_path, "defaultTestDir": '"unmatched'})
    )
    server = TDDServer(project_root=str(suite_dir), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="test_a.py", targetFiles=["test_a.py"])

    call(server, "run_tests")  # red -> verify_green (own target already passes)
    call(server, "verify")  # -> refactor

    payload = call(server, "run_tests")  # closing refactor hits the malformed defaultTestDir

    assert "error" in payload
    assert "defaultTestDir" in payload["error"]
    assert "Traceback" not in payload["error"]


def test_regression_check_attributes_failure_to_refactor_when_own_target_breaks(tmp_path):
    # closing_base_refactor's combined run can fail because the cycle's own
    # test broke, not because of a regression elsewhere. The second
    # (own-target-only) adapter call must attribute that correctly: keep
    # the standard "Refactor broke the tests." message and leave failure
    # names unprefixed (no "REGRESSION:") rather than blaming the rest of
    # the suite.
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "test_a.py").write_text("def test_a1():\n    assert True\n")
    (suite_dir / "test_b.py").write_text("def test_b1():\n    assert True\n")

    adapter_path = str(PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh")
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps({"adapterPath": adapter_path, "defaultTestDir": "."})
    )
    server = TDDServer(project_root=str(suite_dir), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="test_a.py", targetFiles=["test_a.py"])

    call(server, "run_tests")  # red -> verify_green (own target passes)
    call(server, "verify")  # -> refactor

    # Simulate the refactor breaking the cycle's own test.
    (suite_dir / "test_a.py").write_text("def test_a1():\n    assert False\n")

    payload = call(server, "run_tests")  # closes refactor -> regression check runs

    assert payload["phase"] == "refactor"  # blocked: own target broke
    assert payload["lastError"] == "Refactor broke the tests."
    assert not any(
        f["name"].startswith("REGRESSION:")
        for f in payload["testResult"]["failures"]
    )


def test_regression_check_labels_extra_regressions_when_own_target_also_breaks(tmp_path):
    # If BOTH the cycle's own test and something else in the suite are
    # broken at once, the response must distinguish the two: own-target
    # failures stay unprefixed, but the unrelated ones still need their
    # REGRESSION: label — otherwise fixing the own test looks like it
    # would fix everything.
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "test_a.py").write_text("def test_a1():\n    assert True\n")
    (suite_dir / "test_b.py").write_text("def test_b1():\n    assert True\n")

    adapter_path = str(PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh")
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps({"adapterPath": adapter_path, "defaultTestDir": "."})
    )
    server = TDDServer(project_root=str(suite_dir), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="test_a.py", targetFiles=["test_a.py"])

    call(server, "run_tests")  # red -> verify_green (own target passes)
    call(server, "verify")  # -> refactor

    # Break both the cycle's own test and an unrelated one.
    (suite_dir / "test_a.py").write_text("def test_a1():\n    assert False\n")
    (suite_dir / "test_b.py").write_text("def test_b1():\n    assert False\n")

    payload = call(server, "run_tests")  # closes refactor -> regression check runs

    assert payload["phase"] == "refactor"  # blocked: own target broke
    failures = payload["testResult"]["failures"]
    own_failures = [f for f in failures if not f["name"].startswith("REGRESSION:")]
    regression_failures = [f for f in failures if f["name"].startswith("REGRESSION:")]
    assert any("test_a.py" in f["name"] for f in own_failures)
    assert any("test_b.py" in f["name"] for f in regression_failures)
    assert "Refactor broke the tests" in payload["lastError"]
    assert "pre-existing failures elsewhere" in payload["lastError"]


def test_regression_check_returns_error_when_own_target_recheck_adapter_fails(tmp_path):
    # The second (own-target-only) adapter call in the closing-refactor
    # regression check can itself fail to run (crash, timeout, bad output).
    # That must surface as a normal {"error": ...} response, not raise.
    counter_file = tmp_path / "count.txt"
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        f'''#!/usr/bin/env python3
import json
import pathlib
import sys

counter_file = pathlib.Path({str(counter_file)!r})
count = int(counter_file.read_text()) if counter_file.exists() else 0
count += 1
counter_file.write_text(str(count))

if count == 3:
    # Simulate the own-target-only recheck call crashing.
    sys.exit(1)

if count == 2:
    print(json.dumps({{"passed": 0, "failed": 1, "failures": [{{"name": "t", "message": "m"}}]}}))
else:
    print(json.dumps({{"passed": 1, "failed": 0, "failures": []}}))
'''
    )
    fake_adapter.chmod(0o755)

    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps({"adapterPath": str(fake_adapter), "defaultTestDir": "whole/"})
    )
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="own_test.py", targetFiles=["own_test.py"])

    call(server, "run_tests")  # count=1: red -> verify_green (own target passes)
    call(server, "verify")  # -> refactor

    payload = call(server, "run_tests")  # count=2 combined fails, count=3 own-only crashes

    assert "error" in payload
    assert "Adapter failed" in payload["error"]


def test_regression_check_returns_clean_error_for_malformed_failure_entry_during_relabeling(
    tmp_path,
):
    # closing_base_refactor's relabeling step does f["name"]/f["message"] on
    # each combined-run failure once the own-target-only recheck comes back
    # clean (see the REGRESSION: prefixing above). AdapterResult.from_json
    # only checks that failure entries are dicts, not that they carry
    # "name"/"message" keys, so a conforming-but-key-missing dict must
    # surface as a clean AdapterError here too, not an uncaught KeyError.
    counter_file = tmp_path / "count.txt"
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        f'''#!/usr/bin/env python3
import json
import pathlib

counter_file = pathlib.Path({str(counter_file)!r})
count = int(counter_file.read_text()) if counter_file.exists() else 0
count += 1
counter_file.write_text(str(count))

if count == 2:
    # Combined run: one failure, but missing the "name"/"message" keys
    # the relabeling step assumes are present.
    print(json.dumps({{"passed": 0, "failed": 1, "failures": [{{"foo": "bar"}}]}}))
elif count == 3:
    # Own-target-only recheck: clean, so the failure above gets relabeled
    # as a REGRESSION rather than attributed to this refactor.
    print(json.dumps({{"passed": 1, "failed": 0, "failures": []}}))
else:
    print(json.dumps({{"passed": 1, "failed": 0, "failures": []}}))
'''
    )
    fake_adapter.chmod(0o755)

    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps({"adapterPath": str(fake_adapter), "defaultTestDir": "whole/"})
    )
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="own_test.py", targetFiles=["own_test.py"])

    call(server, "run_tests")  # count=1: red -> verify_green (own target passes)
    call(server, "verify")  # -> refactor

    payload = call(server, "run_tests")  # count=2 combined fails, count=3 own-only clean

    assert "error" in payload
    assert "Adapter failed" in payload["error"]


def test_run_tests_caps_failure_count_and_message_length(tmp_path):
    # A big regression check (or any adapter that doesn't cap its own
    # output) shouldn't be free to return an unbounded failures payload —
    # that cost isn't paid once, it's re-sent on every later get_status()
    # too, since last_result stores whatever run_tests() records.
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        '''#!/usr/bin/env python3
import json

failures = [
    {"name": f"t{i}", "message": "x" * 2000} for i in range(30)
]
print(json.dumps({"passed": 0, "failed": len(failures), "failures": failures}))
'''
    )
    fake_adapter.chmod(0o755)

    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(json.dumps({"adapterPath": str(fake_adapter)}))
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="own_test.py", targetFiles=["own_test.py"])

    payload = call(server, "run_tests")
    failures = payload["testResult"]["failures"]

    assert len(failures) == 21  # 20 real + 1 "omitted" marker
    assert all(len(f["message"]) <= 500 for f in failures)
    assert "omitted" in failures[-1]["message"]

    # The cap must stick in state too, not just this one response.
    status_payload = call(server, "get_status")
    assert len(status_payload["lastResult"]["failures"]) == 21


def test_run_tests_keeps_the_tail_of_an_overlong_failure_message(tmp_path):
    # A traceback's actual exception/assertion line is the last thing in
    # it, not the first — cutting the message down to MAX_FAILURE_MESSAGE_
    # CHARS from the front keeps irrelevant call-frame noise and throws
    # away the one line that explains what actually went wrong.
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        '''#!/usr/bin/env python3
import json

failures = [
    {
        "name": "t1",
        "message": ("noise " * 200) + "AssertionError: the real reason",
    }
]
print(json.dumps({"passed": 0, "failed": 1, "failures": failures}))
'''
    )
    fake_adapter.chmod(0o755)

    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(json.dumps({"adapterPath": str(fake_adapter)}))
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="own_test.py", targetFiles=["own_test.py"])

    payload = call(server, "run_tests")
    message = payload["testResult"]["failures"][0]["message"]

    assert len(message) <= 500
    assert message.endswith("AssertionError: the real reason")


def test_run_tests_leaves_a_short_failure_message_unchanged(tmp_path):
    # The common case: most real failure messages are well under
    # MAX_FAILURE_MESSAGE_CHARS. Guards against a future edit to
    # _cap_failures (e.g. reverting to a head-cut, or adding formatting)
    # silently corrupting the majority path while only the >500-char
    # truncation path stays covered.
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        '''#!/usr/bin/env python3
import json

failures = [{"name": "t1", "message": "AssertionError: short and simple"}]
print(json.dumps({"passed": 0, "failed": 1, "failures": failures}))
'''
    )
    fake_adapter.chmod(0o755)

    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(json.dumps({"adapterPath": str(fake_adapter)}))
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="own_test.py", targetFiles=["own_test.py"])

    payload = call(server, "run_tests")
    message = payload["testResult"]["failures"][0]["message"]

    assert message == "AssertionError: short and simple"


def test_run_tests_returns_clean_error_for_malformed_failure_entries(tmp_path):
    # An adapter's failures entries aren't required by adapter_contract.py
    # to be dicts today — a non-dict entry must surface as a clean
    # AdapterError, not crash run_tests() with an uncaught TypeError from
    # _cap_failures's {**f, ...} unpacking.
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        '''#!/usr/bin/env python3
import json

print(json.dumps({"passed": 0, "failed": 1, "failures": ["not a dict"]}))
'''
    )
    fake_adapter.chmod(0o755)

    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(json.dumps({"adapterPath": str(fake_adapter)}))
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="own_test.py", targetFiles=["own_test.py"])

    payload = call(server, "run_tests")

    assert "error" in payload
    assert "Adapter failed" in payload["error"]


def test_run_tests_returns_clean_error_for_failure_entry_missing_message_key(tmp_path):
    # A dict entry with "name" but no "message" is still malformed per the
    # adapter contract — must be rejected the same as a non-dict entry, not
    # let through to crash later on a missing "message" key.
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        '''#!/usr/bin/env python3
import json

print(json.dumps({"passed": 0, "failed": 1, "failures": [{"name": "t"}]}))
'''
    )
    fake_adapter.chmod(0o755)

    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(json.dumps({"adapterPath": str(fake_adapter)}))
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="own_test.py", targetFiles=["own_test.py"])

    payload = call(server, "run_tests")

    assert "error" in payload
    assert "Adapter failed" in payload["error"]


def test_run_tests_does_not_add_omitted_marker_at_exact_cap_boundary(tmp_path):
    # Exactly MAX_FAILURES_RETURNED (20) failures must come back untouched —
    # no synthetic "omitted" entry appended when nothing was actually cut.
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        '''#!/usr/bin/env python3
import json

failures = [{"name": f"t{i}", "message": "boom"} for i in range(20)]
print(json.dumps({"passed": 0, "failed": len(failures), "failures": failures}))
'''
    )
    fake_adapter.chmod(0o755)

    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(json.dumps({"adapterPath": str(fake_adapter)}))
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="own_test.py", targetFiles=["own_test.py"])

    payload = call(server, "run_tests")
    failures = payload["testResult"]["failures"]

    assert len(failures) == 20
    assert all(f["name"] != "..." for f in failures)


def test_run_tests_honors_custom_path_env_when_invoking_adapter(tmp_path, monkeypatch):
    # The adapter shells out to language tools (pytest, npx) by bare name,
    # relying on inherited PATH to resolve the project-pinned version (see
    # .mcp.json's PATH override). run_adapter must not strip/replace the
    # server process's environment before spawning the adapter, or a
    # consumer project's PATH override would silently do nothing.
    marker_dir = tmp_path / "custom-bin"
    marker_dir.mkdir()

    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        f'''#!/usr/bin/env python3
import json
import os

found = {str(marker_dir)!r} in os.environ.get("PATH", "").split(os.pathsep)
print(json.dumps({{"passed": 0, "failed": 1, "failures": [{{"name": "path", "message": "found" if found else "missing"}}]}}))
'''
    )
    fake_adapter.chmod(0o755)

    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(json.dumps({"adapterPath": str(fake_adapter)}))
    server = TDDServer(project_root=str(tmp_path), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile="own_test.py", targetFiles=["own_test.py"])

    monkeypatch.setenv("PATH", f"{marker_dir}{os.pathsep}{os.environ['PATH']}")
    payload = call(server, "run_tests")

    assert payload["testResult"]["failures"][0]["message"] == "found"
