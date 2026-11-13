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


def scope(root, *changed):
    return scope_for_changed_files(VITEST_ADAPTER, str(root), list(changed))


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
