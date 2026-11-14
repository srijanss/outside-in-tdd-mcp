import json
import subprocess

import pytest

from core.server import TDDServer


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


# Echoes the changed files it was given back as the scope.
ECHO_SCOPE = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "print(json.dumps({'scope': ' '.join(sorted(sys.argv[2:]))}))\n"
)

# Like ECHO_SCOPE, but prefixes the scope with TDD_SCOPE_MODE when it is set.
MODE_AWARE_SCOPE = (
    "#!/usr/bin/env python3\n"
    "import json, os, sys\n"
    "mode = os.environ.get('TDD_SCOPE_MODE')\n"
    "files = ' '.join(sorted(sys.argv[2:]))\n"
    "print(json.dumps({'scope': f'{mode}:{files}' if mode else files}))\n"
)


def project(tmp_path, with_scope_script, scope_body=ECHO_SCOPE, extra_config=None):
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir(parents=True)
    run = adapter_dir / "run.sh"
    # Logs each call's arguments, one line per call.
    run.write_text(
        f"#!/bin/sh\necho \"$*\" >> {adapter_dir / 'calls.log'}\n"
        "echo '{\"passed\": 1, \"failed\": 0}'\n"
    )
    run.chmod(0o755)
    if with_scope_script:
        scope = adapter_dir / "scope.sh"
        scope.write_text(scope_body)
        scope.chmod(0o755)

    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("A = 1\n")
    (root / "pkg" / "b.py").write_text("B = 1\n")
    git(root, "init", "-q")
    git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")

    (root / "pkg" / "a.py").write_text("A = 2\n")  # tracked change
    (root / "pkg" / "new.py").write_text("N = 1\n")  # untracked

    config = tmp_path / ".tdd-config.json"
    config.write_text(
        json.dumps(
            {
                "adapterPath": str(run),
                "defaultTestDir": "tests/",
                **(extra_config or {}),
            }
        )
    )
    server = TDDServer(project_root=str(root), config_path=str(config))
    server.call_tool(
        "init_feature",
        {"featureName": "f", "testFile": "tests/test_f.py", "targetFiles": []},
    )
    server.call_tool("run_tests", {})
    server.call_tool("verify", {})
    assert server.sm.phase == "refactor"
    return server


def closing_run(server):
    return json.loads(server.call_tool("run_tests", {})[0].text)


def test_the_suggested_scope_covers_the_changed_files(tmp_path):
    payload = closing_run(project(tmp_path, with_scope_script=True))

    assert payload["needsRegressionScopeConfirmation"] is True
    assert payload["suggestedScope"] == "pkg/a.py pkg/new.py"
    assert payload["fullSuiteScope"] == "tests/"


def test_without_a_scope_script_the_suggestion_is_the_whole_default_test_dir(
    tmp_path,
):
    payload = closing_run(project(tmp_path, with_scope_script=False))

    assert payload["suggestedScope"] == "tests/"
    assert payload["fullSuiteScope"] == "tests/"


def test_a_rename_hands_both_its_source_and_destination_to_the_scope_script(
    tmp_path,
):
    server = project(tmp_path, with_scope_script=True)
    root = tmp_path / "proj"
    (root / "pkg2").mkdir()
    git(root, "mv", "pkg/b.py", "pkg2/b.py")

    payload = closing_run(server)

    assert payload["suggestedScope"] == "pkg/a.py pkg/b.py pkg/new.py pkg2/b.py"


def test_the_response_carries_the_changed_scope_from_a_second_scope_call(tmp_path):
    payload = closing_run(
        project(tmp_path, with_scope_script=True, scope_body=MODE_AWARE_SCOPE)
    )

    assert payload["suggestedScope"] == "pkg/a.py pkg/new.py"
    assert payload["changedScope"] == "changed:pkg/a.py pkg/new.py"
    assert payload["fullSuiteScope"] == "tests/"


def changed_default_run(tmp_path, scope_body=MODE_AWARE_SCOPE, **kwargs):
    return closing_run(
        project(
            tmp_path,
            scope_body=scope_body,
            extra_config={"regressionScopeDefault": "changed"},
            **kwargs,
        )
    )


def test_the_changed_default_suggests_the_changed_scope(tmp_path):
    payload = changed_default_run(tmp_path, with_scope_script=True)

    assert payload["suggestedScope"] == "changed:pkg/a.py pkg/new.py"
    assert payload["changedScope"] == "changed:pkg/a.py pkg/new.py"
    assert payload["fullSuite"] == "gate"


# Prints the "empty" answer under changed mode, the files otherwise.
EMPTY_WHEN_CHANGED_SCOPE = (
    "#!/usr/bin/env python3\n"
    "import json, os, sys\n"
    "if os.environ.get('TDD_SCOPE_MODE') == 'changed':\n"
    "    print(json.dumps({'scope': None, 'empty': True}))\n"
    "else:\n"
    "    print(json.dumps({'scope': ' '.join(sorted(sys.argv[2:]))}))\n"
)


def test_an_empty_changed_scope_suggests_skipping_the_sweep(tmp_path):
    payload = changed_default_run(
        tmp_path, scope_body=EMPTY_WHEN_CHANGED_SCOPE, with_scope_script=True
    )

    assert payload["changedScope"] == "skip"
    assert payload["suggestedScope"] == "skip"


NULL_SCOPE = "#!/bin/sh\necho '{\"scope\": null}'\n"
FAILING_SCOPE = "#!/bin/sh\nexit 1\n"


def test_with_the_changed_default_an_unmapped_change_leaves_the_suite_to_the_gate(
    tmp_path,
):
    for name, kwargs in {
        "null": {"scope_body": NULL_SCOPE, "with_scope_script": True},
        "failing": {"scope_body": FAILING_SCOPE, "with_scope_script": True},
        "missing": {"with_scope_script": False},
    }.items():
        payload = changed_default_run(tmp_path / name, **kwargs)

        assert payload["changedScope"] == "skip", name
        assert payload["suggestedScope"] == "skip", name
        assert "gate" in payload["regressionScopeNote"], name


def test_accepting_a_skip_suggestion_runs_only_the_cycles_own_target(tmp_path):
    server = project(
        tmp_path,
        with_scope_script=True,
        scope_body=NULL_SCOPE,
        extra_config={"regressionScopeDefault": "changed"},
    )
    calls = tmp_path / "adapter" / "calls.log"
    before = calls.read_text().splitlines()

    payload = closing_run(server)

    assert payload["suggestedScope"] == "skip"
    # The confirmation itself runs no tests.
    assert calls.read_text().splitlines() == before

    server.call_tool("run_tests", {"regressionScope": payload["suggestedScope"]})

    last_call = calls.read_text().splitlines()[-1].split()
    assert "tests/test_f.py" in last_call
    assert "tests/" not in last_call
    assert server.sm.phase == "red"


def test_after_a_skip_suggestion_a_failing_own_target_blocks_completion(tmp_path):
    server = project(
        tmp_path,
        with_scope_script=True,
        scope_body=NULL_SCOPE,
        extra_config={"regressionScopeDefault": "changed"},
    )
    payload = closing_run(server)
    (tmp_path / "adapter" / "run.sh").write_text(
        "#!/bin/sh\necho '{\"passed\": 0, \"failed\": 1, "
        "\"failures\": [{\"name\": \"t\", \"message\": \"boom\"}]}'\n"
    )

    server.call_tool("run_tests", {"regressionScope": payload["suggestedScope"]})

    assert server.sm.phase == "refactor"
    done = json.loads(server.call_tool("complete_feature", {})[0].text)
    assert "error" in done


def test_a_script_that_ignores_the_mode_gives_its_broad_scope(tmp_path):
    payload = changed_default_run(
        tmp_path, scope_body=ECHO_SCOPE, with_scope_script=True
    )

    assert payload["changedScope"] == "pkg/a.py pkg/new.py"
    assert payload["suggestedScope"] == "pkg/a.py pkg/new.py"
    assert "regressionScopeNote" not in payload


def test_without_the_changed_default_an_unmapped_change_suggests_the_whole_suite(
    tmp_path,
):
    for name, extra in {"unset": None, "affected": "affected"}.items():
        payload = closing_run(
            project(
                tmp_path / name,
                with_scope_script=True,
                scope_body=NULL_SCOPE,
                extra_config=extra and {"regressionScopeDefault": extra},
            )
        )

        assert payload["suggestedScope"] == "tests/", name
        assert payload["changedScope"] == "tests/", name
        assert "regressionScopeNote" not in payload, name


def test_the_full_default_suggests_the_whole_suite(tmp_path):
    payload = closing_run(
        project(
            tmp_path,
            with_scope_script=True,
            scope_body=MODE_AWARE_SCOPE,
            extra_config={"regressionScopeDefault": "full"},
        )
    )

    assert payload["suggestedScope"] == "tests/"
    assert payload["changedScope"] == "changed:pkg/a.py pkg/new.py"
    assert payload["fullSuiteScope"] == "tests/"


def test_an_invalid_regression_scope_default_is_rejected_at_config_load(tmp_path):
    from core.server import ConfigError, load_config

    for value in ("narrow", "", 1, None):
        config = tmp_path / f"{value!r}.json"
        config.write_text(
            json.dumps({"adapterPath": "run.sh", "regressionScopeDefault": value})
        )
        with pytest.raises(ConfigError, match="'regressionScopeDefault' must be one of"):
            load_config(str(config))

    for value in ("affected", "changed", "full"):
        config = tmp_path / f"{value}.json"
        config.write_text(
            json.dumps({"adapterPath": "run.sh", "regressionScopeDefault": value})
        )
        assert load_config(str(config))["regressionScopeDefault"] == value
