# Working in a git worktree (Claude Code and Codex)

Every piece of per-project config an agent needs — `.mcp.json`,
`.codex/config.toml`, the `.claude/settings.json` hook, and the scripts
they call in `.agents/` — is committed and resolves paths from its own
file location, not a hardcoded absolute path. That's what makes a plain
`git worktree add` usable: once the worktree exists, all of that config
just works, unmodified, for whichever tool you're driving.

The one thing `git worktree add` does *not* give you is a Python
environment: `.venv/` is gitignored (it's machine- and worktree-specific),
so a fresh worktree has none.

## Setup

```bash
git worktree add ../outside-in-tdd-mcp-<name> -b <branch>
cd ../outside-in-tdd-mcp-<name>
.agents/scripts/setup-worktree.sh
```

The script runs `uv sync --extra dev`, which creates `.venv/` and installs
this project into it editable — pointed at *this worktree's* source, not
the main checkout's. That's what the rest of the config depends on:
`.agents/mcp/launch-outside-in-tdd.sh` puts `<worktree>/.venv/bin` first on
`PATH` and execs `outside-in-tdd-mcp` by name (PATH lookup, not a
hardcoded path), so it always runs the worktree's own code. Without a
worktree-local `.venv`, that lookup would silently fall through to
whatever's installed globally at `~/.local/bin` — the launcher only works
correctly for a worktree that has run this setup step.

## Using it

Open the worktree directory in Claude Code or Codex as you normally would
a checkout. Both tools read the same committed `.mcp.json` /
`.codex/config.toml`, and both resolve to this worktree's own MCP server,
adapters, and test-runner-blocking hook — no per-tool or per-worktree
config editing needed.

## Known gaps

- `.venv/` must be (re)created per worktree; it's never shared or synced
  automatically.
- `.tdd-features.json`, `.tdd-research.json`, and `.tdd-session.log` are
  per-worktree state (uncommitted or gitignored) — a worktree started from
  a given commit does not inherit in-flight feature/research state from
  the checkout it was branched from.
