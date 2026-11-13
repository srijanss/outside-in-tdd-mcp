from pathlib import Path

from core.adapter_contract import scope_for_changed_files

CARGO_ADAPTER = str(
    Path(__file__).resolve().parents[1] / "adapters" / "cargo-adapter" / "run.sh"
)


def write(root, files):
    for path, body in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)


def scope(root, *changed):
    return scope_for_changed_files(CARGO_ADAPTER, str(root), list(changed))


WORKSPACE = {
    "Cargo.toml": '[workspace]\nmembers = ["crates/*", "tools/cli"]\n',
    "crates/core/Cargo.toml": '[package]\nname = "core-lib"\n',
    "crates/core/src/lib.rs": "",
    "crates/net/Cargo.toml": '[package]\nname = "net"\n',
    "crates/net/src/lib.rs": "",
    "tools/cli/Cargo.toml": '[package]\nname = "cli"\n',
    "tools/cli/src/main.rs": "",
}


def test_changed_files_map_to_a_package_flag_per_changed_workspace_crate(tmp_path):
    write(tmp_path, WORKSPACE)
    assert (
        scope(
            tmp_path,
            "crates/core/src/lib.rs",
            "tools/cli/src/main.rs",
            "crates/core/tests/it.rs",
        )
        == "-p cli -p core-lib"
    )


def test_workspace_crates_depending_on_a_changed_crate_are_included(tmp_path):
    write(
        tmp_path,
        {
            **WORKSPACE,
            "crates/net/Cargo.toml": '[package]\nname = "net"\n'
            '[dependencies]\ncore-lib = { path = "../core" }\n',
            "tools/cli/Cargo.toml": '[package]\nname = "cli"\n'
            '[target.\'cfg(unix)\'.dev-dependencies]\nnetwork = { package = "net", path = "../../crates/net" }\n',
        },
    )
    assert scope(tmp_path, "crates/core/src/lib.rs") == "-p cli -p core-lib -p net"
    assert scope(tmp_path, "tools/cli/src/main.rs") == "-p cli"


def test_global_files_or_files_outside_every_crate_fall_back_to_the_whole_suite(
    tmp_path,
):
    write(tmp_path, {**WORKSPACE, "scripts/gen.sh": ""})
    for changed in ("Cargo.toml", "Cargo.lock", ".cargo/config.toml", "scripts/gen.sh"):
        assert scope(tmp_path, "crates/net/src/lib.rs", changed) is None, changed
    assert scope(tmp_path, "README.md") is None
    assert scope(tmp_path, "README.md", "crates/net/src/lib.rs") == "-p net"


def test_a_root_package_owns_files_outside_members_and_excluded_members_are_skipped(
    tmp_path,
):
    write(
        tmp_path,
        {
            "Cargo.toml": '[package]\nname = "app"\n'
            '[workspace]\nmembers = ["crates/*"]\nexclude = ["crates/old"]\n',
            "src/main.rs": "",
            "crates/core/Cargo.toml": '[package]\nname = "core-lib"\n',
            "crates/old/Cargo.toml": '[package]\nname = "old"\n',
        },
    )
    assert scope(tmp_path, "src/main.rs", "crates/core/src/lib.rs") == "-p app -p core-lib"
    assert scope(tmp_path, "crates/old/src/lib.rs") == "-p app"


def test_no_root_manifest_or_a_malformed_one_gives_no_mapping(tmp_path):
    assert scope(tmp_path, "src/lib.rs") is None
    write(tmp_path, {"Cargo.toml": "[workspace\n"})
    assert scope(tmp_path, "src/lib.rs") is None


def test_an_inherited_renamed_workspace_dependency_resolves_to_the_real_crate(tmp_path):
    write(
        tmp_path,
        {
            **WORKSPACE,
            "Cargo.toml": '[workspace]\nmembers = ["crates/*", "tools/cli"]\n'
            '[workspace.dependencies]\n'
            'engine = { package = "core-lib", path = "crates/core" }\n',
            "tools/cli/Cargo.toml": '[package]\nname = "cli"\n'
            '[target.\'cfg(unix)\'.build-dependencies]\n'
            'engine = { workspace = true }\n',
        },
    )
    assert scope(tmp_path, "crates/core/src/lib.rs") == "-p cli -p core-lib"


def test_unlisted_path_dependencies_inside_the_workspace_are_members_too(tmp_path):
    write(
        tmp_path,
        {
            "Cargo.toml": '[workspace]\nmembers = ["crates/core", "tools/cli"]\n'
            'exclude = ["vendor"]\n',
            "crates/core/Cargo.toml": '[package]\nname = "core-lib"\n',
            "crates/core/src/lib.rs": "",
            "tools/cli/Cargo.toml": '[package]\nname = "cli"\n[dependencies]\n'
            'helper = { path = "../../libs/helper" }\n'
            'shim = { path = "../../vendor/shim" }\n',
            "tools/cli/src/main.rs": "",
            # Implicit member, reached only through cli's path dependency.
            "libs/helper/Cargo.toml": '[package]\nname = "helper"\n[dependencies]\n'
            'core-lib = { path = "../../crates/core" }\n',
            "libs/helper/src/lib.rs": "",
            # Excluded: not a member even though cli depends on it by path.
            "vendor/shim/Cargo.toml": '[package]\nname = "shim"\n',
            "vendor/shim/src/lib.rs": "",
        },
    )
    assert scope(tmp_path, "crates/core/src/lib.rs") == "-p cli -p core-lib -p helper"
    assert scope(tmp_path, "libs/helper/src/lib.rs") == "-p cli -p helper"
    assert scope(tmp_path, "vendor/shim/src/lib.rs") is None
