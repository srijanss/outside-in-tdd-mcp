#!/usr/bin/env bash
# Worktree-safe launcher for the outside-in-tdd MCP server. Resolves
# TDD_PROJECT_ROOT etc. from this script's own location rather than a
# hardcoded absolute path, so the same committed config (Codex's
# .codex/config.toml) works unmodified in every git worktree/checkout —
# each one has its own copy of this script at the same relative position.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

export TDD_PROJECT_ROOT="$PROJECT_ROOT"
export TDD_CONFIG_PATH="$PROJECT_ROOT/.tdd-config.json"
# Explicit, not just inherited: a bare adapterPath (e.g.
# "pytest-adapter-runner") is resolved via PATH lookup inside the server,
# and $HOME/.local/bin (where `pip install --user -e .` puts console
# scripts) isn't guaranteed to be on whatever PATH the MCP client spawns
# this with.
export PATH="$PROJECT_ROOT/.venv/bin:$HOME/.local/bin:$PATH"

# Resolved via PATH (not a hardcoded ~/.local/bin path) so a worktree with
# its own .venv (see .agents/scripts/setup-worktree.sh) runs its own code;
# only a worktree with no .venv of its own falls through to the global
# ~/.local/bin install.
exec outside-in-tdd-mcp "$@"
