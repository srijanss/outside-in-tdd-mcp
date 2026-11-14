import json
import subprocess

from core.server import TDDServer


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def project(tmp_path, with_scope_script):
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    run = adapter_dir / "run.sh"
    run.write_text("#!/bin/sh\necho '{\"passed\": 1, \"failed\": 0}'\n")
    run.chmod(0o755)
    if with_scope_script:
        # Echoes the changed files it was given back as the scope.
        scope = adapter_dir / "scope.sh"
        scope.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "print(json.dumps({'scope': ' '.join(sorted(sys.argv[2:]))}))\n"
        )
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
        json.dumps({"adapterPath": str(run), "defaultTestDir": "tests/"})
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
