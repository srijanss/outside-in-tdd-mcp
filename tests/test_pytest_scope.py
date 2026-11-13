from pathlib import Path

from core.adapter_contract import scope_for_changed_files

PYTEST_ADAPTER = str(
    Path(__file__).resolve().parents[1] / "adapters" / "pytest-adapter" / "run.sh"
)


def tree(root, *paths):
    for path in paths:
        target = root / path
        if path.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("")


def scope(root, *changed):
    return scope_for_changed_files(PYTEST_ADAPTER, str(root), list(changed))


def test_changed_files_map_to_their_test_files_and_nearest_tests_dirs(tmp_path):
    tree(
        tmp_path,
        "billing/invoice.py",
        "billing/tests/test_invoice.py",
        "shop/cart.py",
        "tests/test_feature.py",
    )

    # The feature's own (changed) test file is kept as itself; a source file
    # maps to the nearest tests/ dir above it, which also absorbs a changed
    # test file inside it.
    assert (
        scope(
            tmp_path,
            "billing/invoice.py",
            "billing/tests/test_invoice.py",
            "tests/test_feature.py",
            "shop/cart.py",
        )
        == "billing/tests tests"
    )


def test_docs_are_ignored_and_deleted_test_files_skipped(tmp_path):
    tree(tmp_path, "pkg/mod.py", "pkg/tests/test_mod.py")
    assert (
        scope(tmp_path, "README.md", "pkg/mod.py", "pkg/tests/test_gone.py")
        == "pkg/tests"
    )


def test_unmappable_or_config_changes_fall_back_to_the_whole_suite(tmp_path):
    tree(tmp_path, "pkg/tests/test_a.py", "lonely/mod.py", "conftest.py")
    assert scope(tmp_path, "lonely/mod.py") is None
    assert scope(tmp_path, "pkg/tests/test_a.py", "pyproject.toml") is None
    assert scope(tmp_path, "conftest.py") is None
    assert scope(tmp_path, "docs.md") is None


def test_a_package_conftest_maps_to_its_directory(tmp_path):
    tree(tmp_path, "pkg/conftest.py", "pkg/tests/test_a.py")
    assert scope(tmp_path, "pkg/conftest.py", "pkg/tests/test_a.py") == "pkg"
