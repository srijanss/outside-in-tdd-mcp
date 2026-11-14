"""covers_full_suite: the adapter's scope.sh --covers-suite answer."""

from core.adapter_contract import covers_full_suite


def adapter(tmp_path, scope_body=None):
    run = tmp_path / "run.sh"
    run.write_text("#!/bin/sh\n")
    run.chmod(0o755)
    if scope_body is not None:
        scope = tmp_path / "scope.sh"
        scope.write_text(scope_body)
        scope.chmod(0o755)
    return str(run)


ECHO_ARGS = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "_, root, scope, suite = sys.argv[1:]\n"
    "print(json.dumps({'coversSuite': scope == suite + ' -v'}))\n"
)


def test_the_answer_comes_from_scope_sh_in_covers_suite_mode(tmp_path):
    run = adapter(tmp_path, ECHO_ARGS)

    assert covers_full_suite(run, str(tmp_path), "tests -v", "tests") is True
    assert covers_full_suite(run, str(tmp_path), "tests -k x", "tests") is False
