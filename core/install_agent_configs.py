"""Console-script entry point that scaffolds .agents/, .claude/, .codex/
(and .mcp.json / .tdd-config.json) into the current directory.

Lets `pip install -e .` put `outside-in-tdd-mcp-install` on PATH as a
stable, project-independent executable — run it from inside any consumer
project instead of reaching back into this repo's checkout. REPO_ROOT
resolves relative to this file's own installed location (like
ADAPTERS_DIR in adapter_entrypoints.py), so it stays correct for an
editable install even if the checkout moves. Only works for an editable
install: a real (non-editable) install doesn't ship these dirs as package
data, since they live outside the `core` package.
"""
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIRS_TO_COPY = (".agents", ".claude", ".codex")
# Both are generic as committed here: .mcp.json points at the self-locating
# .agents/mcp/launch-outside-in-tdd.sh (copied above), and .tdd-config.json's
# adapterPath is the bare "pytest-adapter-runner" console-script name
# (PATH-resolved) rather than an absolute or repo-specific path.
CONFIGS_TO_COPY = (".mcp.json", ".tdd-config.json")


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
    for name in CONFIGS_TO_COPY:
        src = REPO_ROOT / name
        dst = target / name
        if dst.exists():
            print(f"Skipping {name} (already exists in target)")
        else:
            print(f"Copying {name} -> {dst}")
            shutil.copyfile(src, dst)

    print()
    print(f"Done. Next steps in {target}:")
    print(f"  1. If this project isn't pytest-based, update {target / '.tdd-config.json'}")
    print("     (adapter/adapterPath/defaultTestDir — e.g. vitest-adapter-runner for JS/TS).")
    print("  2. Run '/mcp' in Claude Code (or open Codex) here to confirm outside-in-tdd is registered.")
