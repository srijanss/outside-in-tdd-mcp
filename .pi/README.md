# Project-local Pi workflow

All configuration here is project-local. Nothing changes `~/.pi/agent/`.
Run Pi from the repository root and grant project trust. After changes, use
`/reload` (or restart Pi) to reload extensions, instructions and commands.

## Shared hooks

`extensions/workflow-hooks/index.js` adapts Pi's `tool_call` and `tool_result`
events to the command hooks in `.claude/settings.json`. The actual policies
remain in `.agents/hooks/`; there is no separate Pi copy of those scripts.
Requires Bash and jq, like the Claude Code hooks.

- Maps Pi `path` to Claude's `file_path`, and underscored MCP server names
  to the hyphenated names used by the hook matchers.
- Applies to direct tool calls and codemode's nested calls, on any model.
- Runs matching hooks in order, passes session-scoped scratchpad markers,
  and honors JSON denials and nonzero exits. Errors/timeouts fail closed.
- Only successful project-mcp results grant consultation. Each gated TDD
  decision consumes a recent consultation marker, just as in Claude Code.
- Maps Pi grep/find to the shared cold-exploration gate.
- Rejects overlapping TDD state-changing calls. Still await edits, tests and
  phase transitions sequentially; this is not a general scheduler.
- Uses project hooks only, not another copy of global Claude hooks.

The TUI status says **Project workflow hooks enabled** when loaded. If it is
missing, check project trust and extension-loading errors before relying on
these protections. Shell blocklists are heuristics, not a sandbox; aliases,
arbitrary scripts or alternative file-writing tools can bypass them.

Offline regression tests in this source checkout (no model/API calls, no
shared TDD-state mutation):

```sh
node --test .pi/tests/*.test.mjs
```

These integration tests are separate from the project's application suite,
which must run through outside-in-tdd. They use temporary hook scratchpads.
The scaffold test also requires `mcpctl`; it creates an isolated installed-source
fixture and checks copying, config merges, exclusions and re-running init.
Tests are not shipped to consumer projects.

## Commands

In this checkout, `prompts/*.md` are relative symlinks to
`.claude/commands/*.md`; scaffolding copies their contents as regular files.
Pi discovers these as project-local commands, including `/tdd-start`, `/tdd-review`,
`/checkpoint`, and `/catch-up`. Arguments are preserved. The wrappers point
to `.agents/skills/`, which remains the source of detailed instructions.

When adding a Claude command, add its matching relative symlink here. There
are no global prompts, duplicate skills, or extra packages to install.

## Scaffolding into another project

After installing this version with `mcpctl`, run `mcpctl init project-mcp` in
its target project. The `.pi/` directory copy includes the hook adapter,
commands and this guide. It excludes `.pi/tests/` and the JSON configs handled
separately: `.pi/mcp.json` is merged from `.pi/mcp.json.example`, and
`.pi/settings.json` is JSON-merged. Existing values win, and re-running is safe.
The example MCP config itself is not copied. TDD skills and shared safety hook
scripts are supplied by the outside-in-tdd-mcp scaffold, not duplicated here.

## Context and compaction

`settings.json` sets per-model compaction for:

- `claude-bridge/claude-opus-5-5`
- `claude-bridge/claude-sonnet-5-5`

For the currently installed bridge, both register a 1,000,000-token context.
Pi triggers above `contextWindow - reserveTokens`, so `reserveTokens: 850000`
means approximately **150,000 tokens**. Keep-recent retention remains 20,000.
Other models, thinking effort and global settings are unchanged.

This setting also increases the allowed summarization output budget, capped
by the model's output limit; it is a maximum, not a target. Measure actual
usage before tightening further. If the bridge changes its registered window
or you pin a model to 200K, change the reserve accordingly (50,000 for a 200K
window and 150K threshold). Do not blindly copy this value to other models.
Compaction rebuilds the bridge session and can miss the prompt cache; avoid
repeated manual compaction during short cycles.

## Second-model reviews

Keep the implementation session on its original model. Open a **fresh Pi
session** from this repository for Astra or another reviewer. Do not clone or
fork the full implementation transcript just to review.

Example request in the fresh session:

> Review origin/main..HEAD for missing tests, edge/error cases and security.
> Read `.agents/skills/tdd-review/SKILL.md` and its checklist. Use findings
> scope `diff:unpushed`; read existing findings before scanning and persist
> candidates/confirmed findings. Do not implement fixes or modify the active
> TDD feature. If review subagents are unavailable, ask before using a manual
> review.

Back in the original implementation session, ask it to read
`list_review_findings({scope: "diff:unpushed"})`. Transfer findings through the
shared store, not by importing the review transcript or switching the original
session back and forth between providers.

Pi does not currently have an installed review-subagent integration. The roles
in `.claude/agents/review-finder.md` and `review-verifier.md` are available as
instructions for separate sessions, **not automatically executable subagents**.
This setup does not install a delegation package or silently change that review
workflow. Keep concurrent reviewers read-only and avoid starting another TDD
feature while one is active.
