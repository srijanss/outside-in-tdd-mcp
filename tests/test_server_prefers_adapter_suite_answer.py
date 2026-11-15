"""In changed mode the server asks the adapter whether a scope is the full
suite, and falls back to its own check only when the adapter can't tell."""

from tests.test_changed_mode_withholds_full_suite import adapter_calls, sweep
from tests.test_regression_scope_from_changed_files import closing_run, project

# Answers --covers-suite from a table; maps changed files to pkg/ otherwise.
ANSWERING_SCOPE = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "ANSWERS = {'tests -v': True, 'tests/': False, 'pkg': True}\n"
    "if sys.argv[1:2] == ['--covers-suite']:\n"
    "    print(json.dumps({'coversSuite': ANSWERS.get(sys.argv[3])}))\n"
    "else:\n"
    "    print(json.dumps({'scope': 'pkg'}))\n"
)


def answering_project(tmp_path):
    return project(
        tmp_path,
        with_scope_script=True,
        scope_body=ANSWERING_SCOPE,
        extra_config={"regressionScopeDefault": "changed"},
    )


def test_a_scope_the_adapter_says_covers_the_suite_is_refused(tmp_path):
    server = answering_project(tmp_path)
    before = adapter_calls(tmp_path)

    payload = sweep(server, "tests -v")

    assert "gate" in payload.get("error", "")
    assert adapter_calls(tmp_path) == before
