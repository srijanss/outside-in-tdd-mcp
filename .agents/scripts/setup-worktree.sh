#!/usr/bin/env bash
# Provisions a fresh git worktree of this repo: .venv/ is gitignored by
# design (it's machine- and worktree-specific), so a new worktree has none
# until this runs. `uv sync` creates .venv/ and installs this project
# editable (plus dev deps) into it — this is also how the main checkout's
# .venv was built, so worktrees get an identical, isolated environment.
# Run once per new worktree, from anywhere inside it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"
uv sync --extra dev

echo "Worktree ready: $PROJECT_ROOT"
echo "  $(.venv/bin/python --version) -> .venv/"
echo "  MCP server / adapters will resolve to this worktree's own .venv (see .agents/mcp/launch-outside-in-tdd.sh)."
