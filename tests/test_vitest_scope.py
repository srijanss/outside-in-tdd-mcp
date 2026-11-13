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
