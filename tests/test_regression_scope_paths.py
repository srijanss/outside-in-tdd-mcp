"""run_tests' regressionScope: the forms it accepts, the path check before the
adapter is called, and the per-call timeout.
"""

import json
from pathlib import Path

import pytest

import core.server as server_module
from core.adapter_contract import AdapterResult, AdapterTimeoutError, run_adapter
from core.server import ConfigError, TDDServer, load_config
from tests.test_tool_descriptions import listed_tools


def project(tmp_path, files=("tests/test_a.py", "tests/test_b.py"), config=None,
            test_file="tests/test_a.py"):
    """A server at the closing REFACTOR over an adapter that logs each target."""
    adapter = tmp_path / "run.sh"
    adapter.write_text(
        f"#!/bin/sh\necho \"$1\" >> {tmp_path / 'calls.log'}\n"
        "echo '{\"passed\": 1, \"failed\": 0}'\n"
    )
    adapter.chmod(0o755)
    root = tmp_path / "proj"
    root.mkdir()
    for name in files:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("")
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps(
            {
                "adapterPath": str(adapter),
                "defaultTestDir": "tests/",
                **(config or {}),
            }
        )
    )
    server = TDDServer(project_root=str(root), config_path=str(config_path))
    call(server, "init_feature", featureName="f", testFile=test_file, targetFiles=[])
    call(server, "run_tests")
    call(server, "verify")
    assert server.sm.phase == "refactor"
    return server


def call(server, tool, **arguments):
    return json.loads(server.call_tool(tool, arguments)[0].text)


def adapter_targets(tmp_path):
    return (tmp_path / "calls.log").read_text().splitlines()


def test_a_list_a_json_array_string_and_a_spaced_string_give_the_same_adapter_call(
    tmp_path,
):
    paths = ["tests/test_a.py", "tests/test_b.py"]
    targets = {}
    for form, scope in {
        "list": paths,
        "json": json.dumps(paths),
        "spaced": " ".join(paths),
    }.items():
        (tmp_path / form).mkdir()
        server = project(tmp_path / form)

        payload = call(server, "run_tests", regressionScope=scope)

        assert payload["phase"] == "red", (form, payload)
        targets[form] = adapter_targets(tmp_path / form)[-1]

    expected = "tests/test_a.py tests/test_a.py tests/test_b.py"
    assert targets == {"list": expected, "json": expected, "spaced": expected}


@pytest.mark.parametrize(
    "config", [{"testWorkingDir": "src"}, {}], ids=["configured", "inferred"]
)
def test_a_src_prefixed_and_an_unprefixed_path_both_reach_a_run_from_src(
    tmp_path, config
):
    for form, (scope, given) in {
        "prefixed": ("src/tests/test_b.py", "tests/test_b.py"),
        "unprefixed": ("tests/test_b.py", "tests/test_b.py"),
        "node-id": ("src/tests/test_b.py::test_x", "tests/test_b.py::test_x"),
    }.items():
        (tmp_path / form).mkdir()
        server = project(
            tmp_path / form,
            files=("src/tests/test_a.py", "src/tests/test_b.py"),
            config=config,
        )

        payload = call(server, "run_tests", regressionScope=scope)

        assert payload.get("phase") == "red", (form, payload)
        target = adapter_targets(tmp_path / form)[-1]
        assert target == f"tests/test_a.py {given}", form


@pytest.mark.parametrize(
    "files, test_dir",
    [
        (("tests/test_a.py",), ""),
        (("src/tests/test_a.py",), "src"),
    ],
    ids=["root", "src"],
)
def test_an_unknown_path_is_refused_before_any_adapter_call(
    tmp_path, files, test_dir
):
    server = project(tmp_path, files=files)
    before = adapter_targets(tmp_path)
    status = server.sm.status()

    payload = call(
        server,
        "run_tests",
        regressionScope=["tests/test_a.py", "tests/test_gone.py"],
    )

    root = tmp_path / "proj"
    relative_to = f"{root} (or {root / test_dir})" if test_dir else str(root)
    assert payload["error"] == (
        "regressionScope path 'tests/test_gone.py' not found; paths are "
        f"relative to {relative_to}; suggestedScope: tests/"
    )
    assert adapter_targets(tmp_path) == before
    assert server.sm.status() == status


@pytest.mark.parametrize(
    "scope",
    [
        "tests/test_b.py -k smoke",
        "-m 'not slow'",
        "-p some-crate",
        "--workspace",
        "module::tests",
        "related tests/test_b.py",
        "-x tests/test_b.py::test_x",
        "--junitxml out/report.xml.d",
    ],
)
def test_options_and_filter_words_are_not_taken_for_paths(tmp_path, scope):
    server = project(tmp_path)

    payload = call(server, "run_tests", regressionScope=scope)

    assert payload.get("phase") == "red", payload
    assert adapter_targets(tmp_path)[-1] == f"tests/test_a.py {scope}"


@pytest.mark.parametrize("mode", ["affected", "changed"])
@pytest.mark.parametrize(
    "mapped, offered",
    [("src/tests/test_b.py", "tests/test_b.py"), ("src/tests", "tests")],
    ids=["file", "suite"],
)
def test_a_suggested_scope_comes_in_the_form_the_adapter_takes(
    tmp_path, mode, mapped, offered
):
    scope_script = tmp_path / "scope.sh"
    scope_script.write_text(f"#!/bin/sh\necho '{{\"scope\": \"{mapped}\"}}'\n")
    scope_script.chmod(0o755)
    server = project(
        tmp_path,
        files=("src/tests/test_a.py", "src/tests/test_b.py"),
        config={"regressionScopeDefault": mode},
    )
    # scope.sh is only asked when something changed.
    server._changed_paths = lambda **_: ["src/tests/test_b.py"]

    payload = call(server, "run_tests")

    if mode == "changed" and offered == "tests":
        offered = "skip"  # the whole suite is left to the gate
    assert payload["suggestedScope"] == offered
    assert payload["changedScope"] == offered


@pytest.mark.parametrize("mode", ["affected", "changed"])
def test_a_mapped_scope_means_the_root_path_when_the_run_dir_has_it_too(
    tmp_path, mode
):
    scope_script = tmp_path / "scope.sh"
    scope_script.write_text(
        "#!/bin/sh\necho '{\"scope\": \"tests/test_b.py::test_x\"}'\n"
    )
    scope_script.chmod(0o755)
    server = project(
        tmp_path,
        files=("src/tests/test_a.py", "src/tests/test_b.py", "tests/test_b.py"),
        config={"regressionScopeDefault": mode, "testWorkingDir": "src"},
    )
    server._changed_paths = lambda **_: ["tests/test_b.py"]

    suggested = call(server, "run_tests")["suggestedScope"]

    assert suggested == "../tests/test_b.py::test_x"
    # Sent back, it still names that file.
    assert call(server, "run_tests", regressionScope=suggested)["phase"] == "red"
    assert adapter_targets(tmp_path)[-1] == f"tests/test_a.py {suggested}"


@pytest.mark.parametrize("default_test_dir", ["tests/", "src/tests"])
@pytest.mark.parametrize("scope", ["tests", "src/tests", "src", "."])
def test_changed_mode_refuses_the_suite_in_either_spelling_of_a_src_project(
    tmp_path, default_test_dir, scope
):
    server = project(
        tmp_path,
        files=("src/tests/test_a.py",),
        config={
            "regressionScopeDefault": "changed",
            "testWorkingDir": "src",
            "defaultTestDir": default_test_dir,
        },
    )
    before = adapter_targets(tmp_path)

    payload = call(server, "run_tests", regressionScope=scope)

    assert "gate" in payload.get("error", ""), payload
    assert adapter_targets(tmp_path) == before


@pytest.mark.parametrize(
    "spelling", ["{root}/src/tests", "{root}/src", "{root}", "../src/tests", ".."]
)
def test_changed_mode_refuses_the_suite_however_its_path_is_spelled(
    tmp_path, spelling
):
    server = project(
        tmp_path,
        files=("src/tests/test_a.py",),
        config={"regressionScopeDefault": "changed", "testWorkingDir": "src"},
    )
    before = adapter_targets(tmp_path)
    scope = spelling.format(root=tmp_path / "proj")

    payload = call(server, "run_tests", regressionScope=scope)

    assert "gate" in payload.get("error", ""), payload
    assert adapter_targets(tmp_path) == before


@pytest.mark.parametrize(
    "files, target, expected",
    [
        (
            {},
            "{tmp}/test_gone.py",
            "ERROR: file or directory not found: {tmp}/test_gone.py",
        ),
        (
            {
                # Captured output is printed after the traceback.
                "test_noisy.py": "print('noise\\n' * 200)\n"
                "import no_such_module_xyz\n"
            },
            "{tmp}/test_noisy.py",
            "No module named 'no_such_module_xyz'",
        ),
    ],
    ids=["not-found", "import-error"],
)
def test_a_collection_error_reports_pytests_error_line(
    tmp_path, files, target, expected
):
    for name, body in files.items():
        (tmp_path / name).write_text(body)
    repo = Path(__file__).resolve().parents[1]

    result = run_adapter(
        str(repo / "adapters" / "pytest-adapter" / "run.sh"),
        target.format(tmp=tmp_path),
        str(repo),
    )

    assert result.failed == 1
    (failure,) = result.failures
    assert failure["name"] == "collection"
    assert expected.format(tmp=tmp_path) in failure["message"][-500:]
    assert "platform " not in failure["message"]


def test_a_test_working_dir_that_is_no_string_is_rejected_at_config_load(tmp_path):
    path = tmp_path / ".tdd-config.json"
    path.write_text(json.dumps({"adapterPath": "run.sh", "testWorkingDir": 1}))

    with pytest.raises(ConfigError, match="'testWorkingDir' must be"):
        load_config(str(path))


@pytest.mark.parametrize("adapter_times_out", [False, True])
def test_a_timeout_above_the_maximum_is_clamped_with_a_note(
    tmp_path, monkeypatch, adapter_times_out
):
    server = project(tmp_path, config={"maxAdapterTimeoutSeconds": 600})
    seen = []

    def adapter(adapter_path, target, project_root, timeout_s=None):
        seen.append(timeout_s)
        if adapter_times_out:
            raise AdapterTimeoutError("Adapter timed out", timeout_s)
        return AdapterResult(passed=1, failed=0)

    monkeypatch.setattr(server_module, "run_adapter", adapter)

    payload = call(
        server, "run_tests", regressionScope="tests/test_b.py", timeoutSeconds=900
    )

    assert seen == [600]
    assert payload["timeoutNote"] == (
        "timeoutSeconds 900 is above maxAdapterTimeoutSeconds (600); this run "
        "was limited to 600 seconds."
    )
    assert ("error" in payload) is adapter_times_out


def test_a_timeout_within_the_maximum_has_no_note(tmp_path):
    server = project(tmp_path, config={"maxAdapterTimeoutSeconds": 600})

    payload = call(
        server, "run_tests", regressionScope="tests/test_b.py", timeoutSeconds=600
    )

    assert payload["phase"] == "red"
    assert "timeoutNote" not in payload


@pytest.mark.parametrize(
    "config, maximum",
    [
        ({"adapterPath": "run.sh", "maxAdapterTimeoutSeconds": 900}, 900),
        ({"adapterPath": "run.sh"}, 600),
        (None, 600),
    ],
    ids=["configured", "default", "no-config"],
)
def test_the_listed_schema_describes_scope_forms_and_the_configured_maximum(
    tmp_path, monkeypatch, config, maximum
):
    if config is not None:
        (tmp_path / ".tdd-config.json").write_text(json.dumps(config))

    tools = listed_tools(tmp_path, monkeypatch)

    run_tests = next(t for t in tools if t.name == "run_tests")
    properties = run_tests.inputSchema["properties"]
    scope = properties["regressionScope"]["description"]
    for text in (
        "space-separated",
        "JSON array",
        '"skip"',
        "relative to the project root",
        "testWorkingDir",
    ):
        assert text in scope
    timeout = properties["timeoutSeconds"]["description"]
    assert f"maximum here is {maximum}" in timeout
    assert "clamped" in timeout
    assert run_tests.description.endswith("Required parameters: none.")
