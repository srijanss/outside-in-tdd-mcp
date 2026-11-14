from pathlib import Path

from core.adapter_contract import run_adapter, scope_for_changed_files

VITEST_ADAPTER = str(
    Path(__file__).resolve().parents[1] / "adapters" / "vitest-adapter" / "run.sh"
)
FIXTURE_PROJECT = str(Path(__file__).resolve().parent / "fixtures" / "vitest_project")


def test_a_changed_source_file_runs_only_the_tests_importing_it():
    scope = scope_for_changed_files(VITEST_ADAPTER, FIXTURE_PROJECT, ["math.js"])
    assert scope == "related math.js"

    # The fixture's other test files fail; only math.test.js imports math.js.
    result = run_adapter(VITEST_ADAPTER, scope, FIXTURE_PROJECT)
    assert (result.passed, result.failed) == (1, 0)


def write(root, files):
    for path, body in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)


def scope(root, *changed, mode=None):
    return scope_for_changed_files(
        VITEST_ADAPTER, str(root), list(changed), mode=mode
    )


def test_changed_files_map_to_a_sorted_quoted_related_target(tmp_path):
    write(
        tmp_path,
        {
            "src/util.ts": "",
            "src/my file.ts": "",
            "src/app.test.ts": "",
            "styles/theme.css": "",
            "-weird.js": "",
        },
    )
    assert scope(
        tmp_path,
        "src/util.ts",
        "./src/my file.ts",
        "src/app.test.ts",
        "styles/theme.css",
        "-weird.js",
        "docs/guide.md",
        "src/util.ts",
    ) == (
        "related ./-weird.js src/app.test.ts 'src/my file.ts' "
        "src/util.ts styles/theme.css"
    )


def test_config_deleted_sources_docs_only_or_outside_files_give_no_mapping(tmp_path):
    write(tmp_path, {"src/util.ts": "", "src/__tests__/util.ts": ""})
    dotenv = "." + "env"
    for changed in (
        "package.json",
        "pnpm-lock.yaml",
        "tsconfig.build.json",
        "vitest.config.ts",
        "packages/web/vite.config.mjs",
        dotenv,
        dotenv + ".local",
        "src/removed.ts",  # deleted source: its importers can't be found
        "../elsewhere/x.ts",
    ):
        assert scope(tmp_path, "src/util.ts", changed) is None, changed
    assert scope(tmp_path, "README.md", "docs/notes.txt") is None

    # Deleted test files are skipped, not a reason to run everything.
    assert scope(
        tmp_path, "src/util.ts", "src/gone.spec.ts", "src/__tests__/gone.ts"
    ) == "related src/util.ts"
    assert scope(tmp_path, "src/__tests__/util.ts") == "related src/__tests__/util.ts"


def test_files_a_vitest_config_references_and_their_imports_give_no_mapping(tmp_path):
    # setupFiles / globalSetup run around every test without being imported
    # by any, so `vitest related` can't see who they affect.
    write(
        tmp_path,
        {
            "src/util.ts": "",
            "vitest.config.ts": "export default defineConfig({ test: {\n"
            "  setupFiles: ['./tests/init.ts'],\n"
            '  globalSetup: "test-env/boot",\n'
            "}})\n",
            "tests/init.ts": "import { seed } from '../fixtures/seed'\n",
            "fixtures/seed/index.ts": "export const seed = 1\n",
            "test-env/boot.mjs": "const db = require(\"./db.cjs\")\n",
            "test-env/db.cjs": "",
            "packages/web/vite.config.mjs": "export default { test: "
            "{ setupFiles: 'setup/dom.js' } }\n",
            "packages/web/setup/dom.js": "",
            "packages/web/src/app.ts": "",
        },
    )
    for changed in (
        "tests/init.ts",
        "fixtures/seed/index.ts",
        "test-env/boot.mjs",
        "test-env/db.cjs",
        "packages/web/setup/dom.js",
    ):
        assert scope(tmp_path, "src/util.ts", changed) is None, changed
    assert scope(tmp_path, "src/util.ts", "packages/web/src/app.ts") == (
        "related packages/web/src/app.ts src/util.ts"
    )


def test_only_documentation_text_files_are_ignored(tmp_path):
    # .md/.txt/.rst elsewhere may be fixtures read from disk or `?raw`
    # imports, which `vitest related` may not trace: run everything.
    write(
        tmp_path,
        {
            "src/util.ts": "",
            "src/content/intro.md": "",
            "tests/fixtures/expected.txt": "",
            "packages/web/package.json": "{}",
        },
    )
    for changed in ("src/content/intro.md", "tests/fixtures/expected.txt"):
        assert scope(tmp_path, "src/util.ts", changed) is None, changed
    for doc in (
        "README.md",
        "docs/api/usage.rst",
        "packages/web/CHANGELOG.md",
        "packages/web/README.md",
        "LICENSE.txt",
    ):
        assert scope(tmp_path, "src/util.ts", doc) == "related src/util.ts", doc


def test_setup_files_declared_in_an_imported_config_module_give_no_mapping(tmp_path):
    write(
        tmp_path,
        {
            "src/util.ts": "",
            "vitest.config.ts": "import shared from './config/shared'\n"
            "export default mergeConfig(shared, {})\n",
            "config/shared.ts": "import { base } from './base.mjs'\n"
            "export default { ...base, test: { setupFiles: ['tests/init.ts'] } }\n",
            "config/base.mjs": "export const base = { test: "
            "{ globalSetup: './global.ts' } }\n",
            "config/global.ts": "",
            "tests/init.ts": "",
        },
    )
    for changed in ("tests/init.ts", "config/global.ts", "config/shared.ts"):
        assert scope(tmp_path, "src/util.ts", changed) is None, changed


def test_setup_imports_written_with_js_extensions_resolve_to_typescript_sources(
    tmp_path,
):
    write(
        tmp_path,
        {
            "src/util.ts": "",
            "vitest.config.ts": "export default { test: { setupFiles: ['./tests/init.ts'] } }\n",
            "tests/init.ts": "import { db } from './db.js'\nimport './dom.mjs'\n",
            "tests/db.ts": "",
            "tests/dom.mts": "",
        },
    )
    for changed in ("tests/db.ts", "tests/dom.mts"):
        assert scope(tmp_path, "src/util.ts", changed) is None, changed


def test_setup_files_with_unresolvable_bare_imports_give_no_mapping(tmp_path):
    files = {
        "src/util.ts": "",
        "vitest.config.ts": "export default { test: { setupFiles: ['./tests/init.ts'] } }\n",
        "tests/init.ts": "import fs from 'node:fs'\nimport path from 'path'\n"
        "import { expect } from 'vitest'\nimport '@testing-library/jest-dom'\n",
        "node_modules/vitest/package.json": "{}",
        "node_modules/@testing-library/jest-dom/package.json": "{}",
    }
    write(tmp_path, files)
    # Builtins and installed packages are not part of the project.
    assert scope(tmp_path, "src/util.ts") == "related src/util.ts"

    # An alias (resolve.alias / tsconfig paths) may name any project file.
    write(tmp_path, {"tests/init.ts": "import { seed } from '@/fixtures/seed'\n"})
    assert scope(tmp_path, "src/util.ts") is None


def test_build_output_and_vendored_trees_are_not_searched_for_configs(tmp_path):
    files = {"src/util.ts": "", "src/setup.ts": ""}
    for tree in ("dist", "build", "coverage", "out", "target", "vendor", "tmp"):
        files[f"{tree}/pkg/vitest.config.js"] = (
            "export default { test: { setupFiles: ['../../src/setup.ts'] } }\n"
        )
    write(tmp_path, files)
    # Copies of a config in build output don't make src/setup.ts global.
    assert scope(tmp_path, "src/setup.ts") == "related src/setup.ts"


def test_documentation_names_count_only_at_the_root_or_a_package_root(tmp_path):
    # Directory and name conventions alone don't make a file documentation:
    # a root-level prompt.txt or a README.md under fixtures may be test input.
    write(
        tmp_path,
        {
            "src/util.ts": "",
            "prompt.txt": "",
            "tests/fixtures/README.md": "",
            "src/docs/page.md": "",
            "packages/web/package.json": "{}",
        },
    )
    for changed in ("prompt.txt", "tests/fixtures/README.md", "src/docs/page.md"):
        assert scope(tmp_path, "src/util.ts", changed) is None, changed
    for doc in (
        "README.md",
        "LICENSE.txt",
        "docs/api/usage.rst",
        "packages/web/CHANGELOG.md",
        "packages/web/docs/intro.md",
    ):
        assert scope(tmp_path, "src/util.ts", doc) == "related src/util.ts", doc


def test_a_config_importing_an_alias_gives_no_mapping(tmp_path):
    write(
        tmp_path,
        {
            "src/util.ts": "",
            "vitest.config.ts": "import { defineConfig } from 'vitest/config'\n"
            "import shared from '~config/shared'\n"
            "export default defineConfig(shared)\n",
            "node_modules/vitest/package.json": "{}",
        },
    )
    # The aliased module may declare setup files we can't see.
    assert scope(tmp_path, "src/util.ts") is None


def test_a_setup_file_importing_a_linked_workspace_package_gives_no_mapping(tmp_path):
    write(
        tmp_path,
        {
            "src/util.ts": "",
            "vitest.config.ts": "export default { test: { setupFiles: ['./tests/init.ts'] } }\n",
            "tests/init.ts": "import { seed } from '@acme/fixtures'\n",
            "packages/fixtures/package.json": '{"name": "@acme/fixtures"}',
            "packages/fixtures/index.ts": "",
        },
    )
    # Workspace packages are linked into node_modules but are project source.
    (tmp_path / "node_modules/@acme").mkdir(parents=True)
    (tmp_path / "node_modules/@acme/fixtures").symlink_to(
        tmp_path / "packages/fixtures", target_is_directory=True
    )
    assert scope(tmp_path, "src/util.ts", "packages/fixtures/index.ts") is None


def test_a_config_module_shared_by_two_packages_resolves_against_each(tmp_path):
    shared = "import shared from '../../shared/config'\nexport default shared\n"
    write(
        tmp_path,
        {
            "src/util.ts": "",
            "packages/a/vitest.config.ts": shared,
            "packages/b/vitest.config.ts": shared,
            "shared/config.ts": "export default { test: { setupFiles: ['setup.ts'] } }\n",
            "packages/a/setup.ts": "",
            "packages/b/setup.ts": "",
        },
    )
    # setup.ts is relative to each package's config, not the shared module.
    for changed in ("packages/a/setup.ts", "packages/b/setup.ts"):
        assert scope(tmp_path, "src/util.ts", changed) is None, changed


def test_a_setup_file_importing_a_missing_relative_file_gives_no_mapping(tmp_path):
    write(
        tmp_path,
        {
            "src/util.ts": "",
            "vitest.config.ts": "export default { test: { setupFiles: ['./tests/init.ts'] } }\n",
            "tests/init.ts": "import { db } from './db.spec'\n",
        },
    )
    # The deleted dependency looks like a skippable deleted test, but the
    # setup file that imports it now fails for every test.
    assert scope(tmp_path, "src/util.ts", "tests/db.spec.ts") is None
    assert scope(tmp_path, "src/util.ts") is None


def test_changed_mode_runs_direct_importers_but_not_transitive_ones(tmp_path):
    write(
        tmp_path,
        {
            "src/price.ts": "export const price = 1\n",
            "src/cart.ts": "import { price } from './price'\n",
            "src/price.test.ts": "import { price } from './price'\n",
            "src/cart.test.ts": "import { cart } from './cart'\n",
            "tests/__tests__/total.ts": 'const { price } = require("../../src/price.ts")\n',
        },
    )
    assert scope(tmp_path, "src/price.ts", mode="changed") == (
        "src/price.test.ts tests/__tests__/total.ts"
    )


def test_changed_mode_counts_re_exports_and_dynamic_imports(tmp_path):
    write(
        tmp_path,
        {
            "src/price.ts": "",
            "src/barrel.spec.ts": "export * from './price'\n",
            "src/lazy.test.ts": "const m = await import('./price.js')\n",
            "src/other.test.ts": "import './unrelated'\n",
        },
    )
    assert scope(tmp_path, "src/price.ts", mode="changed") == (
        "src/barrel.spec.ts src/lazy.test.ts"
    )


def test_changed_mode_resolves_a_directory_import_to_its_index(tmp_path):
    write(
        tmp_path,
        {
            "src/shop/index.ts": "",
            "src/shop.test.ts": "import { shop } from './shop'\n",
        },
    )
    assert scope(tmp_path, "src/shop/index.ts", mode="changed") == "src/shop.test.ts"


def test_changed_mode_still_gives_no_mapping_for_a_changed_setup_file(tmp_path):
    write(
        tmp_path,
        {
            "src/util.ts": "",
            "src/util.test.ts": "import './util'\n",
            "vitest.config.ts": "export default { test: { setupFiles: ['./tests/init.ts'] } }\n",
            "tests/init.ts": "",
        },
    )
    assert scope(tmp_path, "src/util.ts", "tests/init.ts", mode="changed") is None
    assert scope(tmp_path, "src/util.ts", "package.json", mode="changed") is None
    assert scope(tmp_path, "src/util.ts", "src/gone.ts", mode="changed") is None


def test_changed_mode_gives_empty_when_no_test_imports_the_changed_file(tmp_path):
    write(
        tmp_path,
        {
            "src/util.ts": "",
            "src/orphan.ts": "",
            "src/util.test.ts": "import './util'\n",
        },
    )
    assert scope(tmp_path, "src/orphan.ts", mode="changed") == "skip"
    # A changed test file that still exists runs itself; a deleted one adds nothing.
    assert scope(
        tmp_path, "src/orphan.ts", "src/util.test.ts", "src/gone.test.ts", mode="changed"
    ) == "src/util.test.ts"


def test_changed_mode_ignores_test_files_under_skipped_directories(tmp_path):
    files = {"src/util.ts": "", "src/util.test.ts": "import './util'\n"}
    for tree in ("node_modules/pkg", "dist", ".cache", "vendor/lib"):
        files[f"{tree}/util.test.ts"] = "import '../src/util'\nimport '../../src/util'\n"
    write(tmp_path, files)
    assert scope(tmp_path, "src/util.ts", mode="changed") == "src/util.test.ts"


def test_changed_mode_runs_the_importers_of_a_changed_test_helper(tmp_path):
    # Files under __tests__/ count as tests, but are often shared helpers.
    write(
        tmp_path,
        {
            "src/__tests__/helpers.ts": "",
            "src/__tests__/cart.ts": "import { make } from './helpers'\n",
            "src/price.test.ts": "import { make } from './__tests__/helpers'\n",
        },
    )
    assert scope(tmp_path, "src/__tests__/helpers.ts", mode="changed") == (
        "src/__tests__/cart.ts src/__tests__/helpers.ts src/price.test.ts"
    )


def test_changed_mode_runs_a_test_that_re_exports_a_changed_test(tmp_path):
    write(
        tmp_path,
        {
            "src/cart.spec.ts": "",
            "src/all.test.ts": "export * from './cart.spec'\n",
        },
    )
    assert scope(tmp_path, "src/cart.spec.ts", mode="changed") == (
        "src/all.test.ts src/cart.spec.ts"
    )


def test_without_the_mode_the_scope_is_still_related(tmp_path):
    write(tmp_path, {"src/util.ts": "", "src/util.test.ts": "import './util'\n"})
    assert scope(tmp_path, "src/util.ts") == "related src/util.ts"
    assert scope(tmp_path, "src/util.ts", mode="broad") == "related src/util.ts"
