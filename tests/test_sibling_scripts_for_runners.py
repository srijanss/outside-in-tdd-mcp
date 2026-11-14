"""An installed console runner (e.g. ``pytest-adapter-runner`` in a venv's
bin/) has no scope.sh / recreate-db.sh next to it: the bundled adapter's
companion scripts are used instead."""

from core.adapter_contract import scope_for_changed_files


def test_an_installed_pytest_runner_uses_the_bundled_scope_script(tmp_path):
    runner = tmp_path / "venv" / "bin" / "pytest-adapter-runner"
    runner.parent.mkdir(parents=True)
    runner.write_text("")
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "tests" / "test_cart.py").write_text("")

    scope = scope_for_changed_files(
        str(runner), str(project), ["tests/test_cart.py"]
    )

    assert scope == "tests/test_cart.py"


def test_an_unknown_runner_name_without_siblings_has_no_scope(tmp_path):
    runner = tmp_path / "bin" / "my-adapter-runner"
    runner.parent.mkdir(parents=True)
    runner.write_text("")

    assert scope_for_changed_files(str(runner), str(tmp_path), ["a.py"]) is None
