import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = PROJECT_ROOT / "adapters" / "cargo-adapter" / "run.sh"

FAKE_CARGO = """#!/bin/sh
printf '%s\\n' "$@" > "$ARGS_FILE"
printf '%s\\n' 'running 1 test'
printf '%s\\n' 'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s'
"""


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "ws"
    _write(root / "Cargo.toml", '[workspace]\nmembers = ["crates/*"]\n')
    _write(
        root / "crates" / "alpha_dir" / "Cargo.toml",
        '[package]\nname = "alpha-pkg"  # the crate\nversion = "0.1.0"\n\n'
        '[dependencies]\nname = "ignored"\n',
    )
    _write(root / "crates" / "alpha_dir" / "tests" / "flat.rs")
    _write(root / "crates" / "alpha_dir" / "tests" / "nested" / "main.rs")
    _write(root / "crates" / "alpha_dir" / "src" / "lib.rs")
    _write(
        root / "Cargo.toml",
        '[package]\nname = "rootpkg"\nversion = "0.1.0"\n',
    )
    _write(root / "tests" / "top.rs")
    _write(root / "tests" / "topdir" / "main.rs")
    return root


def run_cargo_args(workspace: Path, tmp_path: Path, target: str) -> list[str]:
    bin_dir = tmp_path / "bin"
    cargo = bin_dir / "cargo"
    _write(cargo, FAKE_CARGO)
    cargo.chmod(0o755)
    args_file = tmp_path / "args.txt"
    env = {**os.environ, "CARGO": str(cargo), "ARGS_FILE": str(args_file)}
    proc = subprocess.run(
        [sys.executable, str(ADAPTER), target, str(workspace)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert json.loads(proc.stdout)["passed"] == 1
    return args_file.read_text().split("\n")[:-1]


def test_path_target_becomes_package_and_test_flags(workspace, tmp_path):
    args = run_cargo_args(workspace, tmp_path, "crates/alpha_dir/tests/flat.rs")

    assert args == ["test", "-p", "alpha-pkg", "--test", "flat"]


def test_main_rs_in_test_directory_maps_to_directory_name(workspace, tmp_path):
    args = run_cargo_args(workspace, tmp_path, "crates/alpha_dir/tests/nested/main.rs")

    assert args == ["test", "-p", "alpha-pkg", "--test", "nested"]


def test_root_crate_test_file_maps_using_root_manifest(workspace, tmp_path):
    assert run_cargo_args(workspace, tmp_path, "tests/top.rs") == [
        "test", "-p", "rootpkg", "--test", "top",
    ]
    assert run_cargo_args(workspace, tmp_path, "tests/topdir/main.rs") == [
        "test", "-p", "rootpkg", "--test", "topdir",
    ]


def test_other_tokens_pass_through_unchanged(workspace, tmp_path):
    args = run_cargo_args(
        workspace, tmp_path, "-p alpha-pkg --test flat some_filter -- --nocapture"
    )

    assert args == [
        "test", "-p", "alpha-pkg", "--test", "flat", "some_filter", "--", "--nocapture",
    ]


def test_path_token_mixed_with_other_tokens_is_replaced_in_place(workspace, tmp_path):
    args = run_cargo_args(
        workspace, tmp_path, "crates/alpha_dir/tests/flat.rs -- --nocapture"
    )

    assert args == ["test", "-p", "alpha-pkg", "--test", "flat", "--", "--nocapture"]


def test_path_shaped_filter_after_double_dash_is_not_translated(workspace, tmp_path):
    args = run_cargo_args(workspace, tmp_path, "-- tests/top.rs")

    assert args == ["test", "--", "tests/top.rs"]


def test_nonexistent_or_unmappable_paths_pass_through(workspace, tmp_path):
    assert run_cargo_args(workspace, tmp_path, "crates/alpha_dir/tests/missing.rs") == [
        "test", "crates/alpha_dir/tests/missing.rs",
    ]
    assert run_cargo_args(workspace, tmp_path, "crates/alpha_dir/src/lib.rs") == [
        "test", "crates/alpha_dir/src/lib.rs",
    ]
