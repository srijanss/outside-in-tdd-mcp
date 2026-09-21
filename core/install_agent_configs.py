"""Scaffolds .agents/, .claude/, .codex/ (and .mcp.json / .tdd-config.json)
into a consumer project.

Run it through mcpctl from inside the project (or pass a target path):

    mcpctl run outside-in-tdd-mcp install [target]

(`outside-in-tdd-mcp-install` is the equivalent console script for a plain
editable install.) REPO_ROOT resolves relative to this file's own installed
location (like ADAPTERS_DIR in adapter_entrypoints.py), so it is correct for
mcpctl's `uv sync` install and for an editable install. A real
(non-editable) install doesn't ship these dirs as package data, since they
live outside the `core` package.
"""
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIRS_TO_COPY = (".agents", ".claude", ".codex")
# (source in this repo, destination in the target). Both are generic as
# committed here: .mcp.example.json runs the server through
# `mcpctl run outside-in-tdd-mcp` (project root defaults to the cwd; the same
# file works on the host and in Docker), and .tdd-config.json's adapterPath
# is the bare "pytest-adapter-runner" console-script name (PATH-resolved,
# falling back to the server interpreter's bin dir) rather than an absolute
# or repo-specific path.
CONFIGS_TO_COPY = (
    (".mcp.example.json", ".mcp.json"),
    (".tdd-config.json", ".tdd-config.json"),
)


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()

    if target == REPO_ROOT:
        sys.exit("Target is this repo itself — nothing to do.")

    for name in DIRS_TO_COPY:
        src = REPO_ROOT / name
        dst = target / name
        print(f"Copying {name}/ -> {dst}/")
        shutil.copytree(
            src,
            dst,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("worktrees"),
        )

    # Never overwrite a config the target project already has of its own.
    for src_name, name in CONFIGS_TO_COPY:
        src = REPO_ROOT / src_name
        dst = target / name
        if dst.exists():
            print(f"Skipping {name} (already exists in target)")
        else:
            print(f"Copying {src_name} -> {dst}")
            shutil.copyfile(src, dst)
            if name == ".tdd-config.json" and (target / "Cargo.toml").exists():
                dst.write_text(
                    json.dumps(
                        {
                            "adapter": "cargo-adapter",
                            "adapterPath": "cargo-adapter-runner",
                            "defaultTestDir": "--workspace",
                        },
                        indent=2,
                    )
                    + "\n"
                )

    print()
    print(f"Done. Next steps in {target}:")
    print(f"  1. If this project isn't pytest- or Cargo-based, update {target / '.tdd-config.json'}")
    print("     (adapter/adapterPath/defaultTestDir — e.g. vitest-adapter-runner for JS/TS).")
    print("  2. Run '/mcp' in Claude Code (or open Codex) here to confirm outside-in-tdd is registered.")
