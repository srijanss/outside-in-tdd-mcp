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


def scope(root, *changed, mode=None):
    return scope_for_changed_files(
        PYTEST_ADAPTER, str(root), list(changed), mode=mode
    )


def write(root, files):
    for path, body in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)


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


def test_dependency_manifests_fall_back_to_the_whole_suite(tmp_path):
    tree(tmp_path, "pkg/tests/test_a.py")
    for manifest in (
        "requirements.txt",
        "requirements-dev.txt",
        "constraints.txt",
        "setup.py",
        "uv.lock",
        "poetry.lock",
        "Pipfile.lock",
    ):
        assert scope(tmp_path, "pkg/tests/test_a.py", manifest) is None, manifest
    assert scope(tmp_path, "pkg/tests/test_a.py", "NOTES.txt") == "pkg/tests/test_a.py"


def test_targets_starting_with_a_dash_are_not_read_as_pytest_options(tmp_path):
    import shlex

    tree(tmp_path, "--collect-only/conftest.py", "-k/tests/test_x.py")
    assert shlex.split(
        scope(tmp_path, "--collect-only/conftest.py", "-k/tests/test_x.py")
    ) == ["./--collect-only", "./-k/tests/test_x.py"]


def test_lone_test_files_are_their_own_targets_and_round_trip_through_shlex(
    tmp_path,
):
    import shlex

    files = ["a/test_one.py", "b/two_test.py", "c d/test_sp ace.py", "e/test_it's.py"]
    tree(tmp_path, *files)
    assert shlex.split(scope(tmp_path, *files)) == sorted(files)


def test_changed_mode_gives_only_the_test_files_importing_a_changed_module(
    tmp_path,
):
    write(
        tmp_path,
        {
            "shop/__init__.py": "",
            "shop/cart.py": "",
            "shop/price.py": "",
            "tests/test_cart.py": "import shop.cart\n",
            "tests/test_price.py": "import shop.price\n",
            "tests/test_misc.py": "import os\n",
        },
    )
    assert scope(tmp_path, "shop/cart.py", mode="changed") == "tests/test_cart.py"


def test_changed_mode_finds_from_imports_and_relative_imports(tmp_path):
    write(
        tmp_path,
        {
            "shop/__init__.py": "",
            "shop/cart.py": "",
            "shop/tests/__init__.py": "",
            "shop/tests/test_from_pkg.py": "from shop import cart\n",
            "shop/tests/test_from_mod.py": "from shop.cart import Cart\n",
            "shop/tests/test_relative.py": "from ..cart import Cart\n",
            "shop/tests/test_relative_pkg.py": "from .. import cart\n",
            "shop/tests/test_other.py": "from shop import price\nfrom . import cart\n",
        },
    )
    assert scope(tmp_path, "shop/cart.py", mode="changed") == " ".join(
        [
            "shop/tests/test_from_mod.py",
            "shop/tests/test_from_pkg.py",
            "shop/tests/test_relative.py",
            "shop/tests/test_relative_pkg.py",
        ]
    )


def test_changed_mode_maps_a_src_layout_module_to_its_package_name(tmp_path):
    write(
        tmp_path,
        {
            "src/shop/__init__.py": "",
            "src/shop/cart.py": "",
            "tests/test_cart.py": "from shop.cart import Cart\n",
            "tests/test_src.py": "import src.shop\n",
        },
    )
    assert scope(tmp_path, "src/shop/cart.py", mode="changed") == "tests/test_cart.py"


def test_changed_mode_gives_empty_when_no_test_imports_the_changed_module(
    tmp_path,
):
    write(
        tmp_path,
        {
            "shop/__init__.py": "",
            "shop/cart.py": "",
            "tests/test_misc.py": "import os\n",
        },
    )
    assert scope(tmp_path, "shop/cart.py", mode="changed") == "skip"
    assert scope(tmp_path, "README.md", mode="changed") == "skip"


def test_changed_mode_keeps_null_for_pytest_config_and_dependency_files(tmp_path):
    write(
        tmp_path,
        {
            "shop/__init__.py": "",
            "shop/cart.py": "",
            "tests/test_cart.py": "import shop.cart\n",
        },
    )
    for name in ("pyproject.toml", "pytest.ini", "requirements.txt", "uv.lock"):
        assert scope(tmp_path, name, mode="changed") is None, name
        assert scope(tmp_path, "shop/cart.py", name, mode="changed") is None, name


def test_changed_mode_keeps_changed_test_files_and_conftest_dirs(tmp_path):
    write(
        tmp_path,
        {
            "shop/__init__.py": "",
            "shop/cart.py": "",
            "shop/conftest.py": "",
            "shop/tests/test_cart.py": "import shop.cart\n",
            "tests/test_feature.py": "",
            "conftest.py": "",
        },
    )
    assert (
        scope(tmp_path, "tests/test_feature.py", "tests/test_gone.py", mode="changed")
        == "tests/test_feature.py"
    )
    # The conftest's directory absorbs the importer found inside it.
    assert (
        scope(tmp_path, "shop/conftest.py", "shop/cart.py", mode="changed") == "shop"
    )
    assert scope(tmp_path, "conftest.py", mode="changed") is None


def test_changed_mode_skips_test_files_that_do_not_parse(tmp_path):
    write(
        tmp_path,
        {
            "shop/__init__.py": "",
            "shop/cart.py": "",
            "tests/test_broken.py": "def oops(:\n",
            "tests/test_cart.py": "import shop.cart\n",
        },
    )
    (tmp_path / "tests/test_binary.py").write_bytes(b"\xff\xfe\x00import shop.cart")
    assert scope(tmp_path, "shop/cart.py", mode="changed") == "tests/test_cart.py"


def test_changed_mode_scans_only_the_default_test_dirs_when_configured(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("TDD_CONFIG_PATH", raising=False)
    write(
        tmp_path,
        {
            ".tdd-config.json": '{"defaultTestDir": "suite/ ../outside"}',
            "shop/__init__.py": "",
            "shop/cart.py": "",
            "suite/unit/test_cart.py": "import shop.cart\n",
            "tests/test_cart.py": "import shop.cart\n",
        },
    )
    assert (
        scope(tmp_path, "shop/cart.py", mode="changed") == "suite/unit/test_cart.py"
    )
    # TDD_CONFIG_PATH, as the server itself reads it, wins.
    write(tmp_path, {"other.json": '{"defaultTestDir": "tests"}'})
    monkeypatch.setenv("TDD_CONFIG_PATH", str(tmp_path / "other.json"))
    assert scope(tmp_path, "shop/cart.py", mode="changed") == "tests/test_cart.py"


def test_changed_mode_does_not_follow_symlinks_out_of_the_project(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("TDD_CONFIG_PATH", raising=False)
    project, outside = tmp_path / "project", tmp_path / "outside"
    write(outside, {"test_far.py": "import shop.cart\n"})
    write(
        project,
        {
            ".tdd-config.json": '{"defaultTestDir": "linked suite"}',
            "shop/__init__.py": "",
            "shop/cart.py": "",
            "suite/test_cart.py": "import shop.cart\n",
        },
    )
    (project / "linked").symlink_to(outside, target_is_directory=True)
    (project / "suite/test_far.py").symlink_to(outside / "test_far.py")
    assert scope(project, "shop/cart.py", mode="changed") == "suite/test_cart.py"


def test_changed_mode_ignores_tests_inside_virtualenvs_and_node_modules(tmp_path):
    write(
        tmp_path,
        {
            "shop/__init__.py": "",
            "shop/cart.py": "",
            "tests/test_cart.py": "import shop.cart\n",
            "venv/lib/site-packages/dep/tests/test_dep.py": "import shop.cart\n",
            "node_modules/x/tests/test_x.py": "import shop.cart\n",
            "__pycache__/tests/test_cached.py": "import shop.cart\n",
        },
    )
    assert scope(tmp_path, "shop/cart.py", mode="changed") == "tests/test_cart.py"


def test_changed_mode_ignores_relative_imports_beyond_the_top_package(tmp_path):
    write(
        tmp_path,
        {
            "cart.py": "",
            "shop/__init__.py": "",
            "shop/tests/__init__.py": "",
            "shop/tests/test_beyond.py": "from ...cart import Cart\n",
            "tests/test_cart.py": "import cart\n",
        },
    )
    assert scope(tmp_path, "cart.py", mode="changed") == "tests/test_cart.py"


def test_changed_mode_maps_a_package_init_to_everything_importing_the_package(
    tmp_path,
):
    write(
        tmp_path,
        {
            "shop/__init__.py": "",
            "shop/cart.py": "",
            "shopping/__init__.py": "",
            "tests/test_pkg.py": "import shop\n",
            "tests/test_sub.py": "import shop.cart\n",
            "tests/test_from.py": "from shop.cart import Cart\n",
            "tests/test_other.py": "import shopping\n",
        },
    )
    assert scope(tmp_path, "shop/__init__.py", mode="changed") == " ".join(
        ["tests/test_from.py", "tests/test_pkg.py", "tests/test_sub.py"]
    )


def test_changed_mode_maps_a_deleted_package_init_to_the_package_importers(
    tmp_path,
):
    write(
        tmp_path,
        {
            "shop/cart.py": "",
            "tests/test_pkg.py": "import shop\n",
            "tests/test_sub.py": "from shop.cart import Cart\n",
            "tests/test_misc.py": "import os\n",
        },
    )
    # shop/__init__.py was deleted: it is not on disk.
    assert scope(tmp_path, "shop/__init__.py", mode="changed") == " ".join(
        ["tests/test_pkg.py", "tests/test_sub.py"]
    )


def test_changed_mode_finds_importers_of_namespace_package_modules(tmp_path):
    write(
        tmp_path,
        {
            "shop/cart.py": "",
            "src/store/deep/item.py": "",
            "tests/test_cart.py": "from shop.cart import Cart\n",
            "tests/test_item.py": "import store.deep.item\n",
            "tests/test_misc.py": "import shop.price\n",
        },
    )
    assert scope(tmp_path, "shop/cart.py", mode="changed") == "tests/test_cart.py"
    assert (
        scope(tmp_path, "src/store/deep/item.py", mode="changed")
        == "tests/test_item.py"
    )


def test_without_the_mode_the_scope_is_still_the_nearest_tests_dir(tmp_path):
    write(
        tmp_path,
        {
            "shop/__init__.py": "",
            "shop/cart.py": "",
            "shop/tests/test_cart.py": "import shop.cart\n",
            "shop/tests/test_misc.py": "import os\n",
            "lonely.py": "",
        },
    )
    assert scope(tmp_path, "shop/cart.py") == "shop/tests"
    assert scope(tmp_path, "shop/cart.py", mode="changed") == "shop/tests/test_cart.py"
    assert scope(tmp_path, "README.md") is None
    assert scope(tmp_path, "lonely.py") is None
