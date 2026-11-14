"""With regressionScopeDefault "changed" the full suite runs at the
orchestrator's gate: the closing-REFACTOR sweep neither offers it nor runs it.
"""

import json

from tests.test_regression_scope_from_changed_files import (
    MODE_AWARE_SCOPE,
    NULL_SCOPE,
    closing_run,
    project,
)


def changed_project(tmp_path, **kwargs):
    return project(
        tmp_path,
        with_scope_script=True,
        scope_body=MODE_AWARE_SCOPE,
        extra_config={"regressionScopeDefault": "changed", **kwargs},
    )


def test_changed_mode_withholds_the_full_suite_scope(tmp_path):
    payload = closing_run(changed_project(tmp_path))

    assert payload["needsRegressionScopeConfirmation"] is True
    assert "fullSuiteScope" not in payload
    assert payload["fullSuite"] == "gate"


def test_an_unmapped_change_in_changed_mode_withholds_the_full_suite_scope(
    tmp_path,
):
    payload = closing_run(
        project(
            tmp_path,
            with_scope_script=True,
            scope_body=NULL_SCOPE,
            extra_config={"regressionScopeDefault": "changed"},
        )
    )

    assert payload["suggestedScope"] == "skip"
    assert "fullSuiteScope" not in payload
    assert payload["fullSuite"] == "gate"


def sweep(server, scope):
    return json.loads(
        server.call_tool("run_tests", {"regressionScope": scope})[0].text
    )


def adapter_calls(tmp_path):
    return (tmp_path / "adapter" / "calls.log").read_text().splitlines()


def test_changed_mode_refuses_a_full_suite_regression_scope(tmp_path):
    server = changed_project(tmp_path)
    before = adapter_calls(tmp_path)

    payload = sweep(server, "tests/")

    assert "gate" in payload["error"]
    assert adapter_calls(tmp_path) == before
    assert server.sm.phase == "refactor"


def test_changed_mode_refuses_other_spellings_of_the_full_suite(tmp_path):
    for name, scope in {
        "no-slash": "tests",
        "dot-prefix": "./tests/",
        "padded": "  tests/  ",
        "plus-extra": "pkg/a.py tests/",
        "project-root": ".",
    }.items():
        server = changed_project(tmp_path / name)
        before = adapter_calls(tmp_path / name)

        payload = sweep(server, scope)

        assert "gate" in payload.get("error", ""), name
        assert adapter_calls(tmp_path / name) == before, name
        assert server.sm.phase == "refactor", name


def test_an_option_value_in_default_test_dir_is_not_a_suite_path(tmp_path):
    for name, default_test_dir in {
        "separate-value": "tests -k smoke",
        "joined-value": "tests --deselect=tests/test_slow.py",
        "option-first": "-k smoke tests",
    }.items():
        server = changed_project(tmp_path / name, defaultTestDir=default_test_dir)
        (tmp_path / name / "proj" / "tests").mkdir()
        before = adapter_calls(tmp_path / name)

        payload = sweep(server, "tests")

        assert "gate" in payload.get("error", ""), name
        assert adapter_calls(tmp_path / name) == before, name


def test_a_bare_option_value_that_is_no_path_is_skipped(tmp_path):
    from core.server import _covers_full_suite

    (tmp_path / "tests").mkdir()

    assert _covers_full_suite("tests", "tests -k smoke", str(tmp_path))
    assert _covers_full_suite("tests", "-x tests", str(tmp_path))


def test_a_scope_with_its_own_options_counts_as_narrowed(tmp_path):
    from core.server import _covers_full_suite

    for scope in ("tests -k smoke", "tests --deselect=tests/test_slow.py"):
        assert not _covers_full_suite(scope, "tests", str(tmp_path)), scope


def test_changed_mode_still_runs_narrower_scopes_and_skip(tmp_path):
    for name, scope, expected in [
        ("file", "tests/test_x.py", "tests/test_x.py"),
        ("subdir", "tests/unit", "tests/unit"),
        ("sibling-prefix", "tests_other/", "tests_other/"),
        ("skip", "skip", None),
    ]:
        server = changed_project(tmp_path / name)

        payload = sweep(server, scope)

        assert "error" not in payload, name
        last_call = adapter_calls(tmp_path / name)[-1].split()
        assert "tests/test_f.py" in last_call, name
        assert "tests/" not in last_call, name
        if expected:
            assert expected in last_call, name
        assert server.sm.phase == "red", name


def test_affected_and_full_modes_still_offer_and_run_the_full_suite(tmp_path):
    for name, extra in {
        "unset": {},
        "affected": {"regressionScopeDefault": "affected"},
        "full": {"regressionScopeDefault": "full"},
    }.items():
        server = project(
            tmp_path / name,
            with_scope_script=True,
            scope_body=MODE_AWARE_SCOPE,
            extra_config=extra,
        )

        payload = closing_run(server)
        assert payload["fullSuiteScope"] == "tests/", name
        assert "fullSuite" not in payload, name

        payload = sweep(server, payload["fullSuiteScope"])

        assert "error" not in payload, name
        assert "tests/" in adapter_calls(tmp_path / name)[-1].split(), name
        assert server.sm.phase == "red", name


def test_the_run_tests_description_says_changed_mode_leaves_the_suite_to_the_gate():
    from core.server import TOOLS

    run_tests = next(t for t in TOOLS if t.name == "run_tests")
    scope_doc = run_tests.inputSchema["properties"]["regressionScope"]["description"]

    for text in (run_tests.description, scope_doc):
        assert "fullSuite: \"gate\"" in text
        assert "refused" in text
