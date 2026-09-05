# Outside-In TDD MCP Server

A language-agnostic MCP server that enforces Outside-In TDD (RED →
VERIFY_RED → IMPLEMENT → VERIFY_GREEN → REFACTOR) when using Claude Code.
The core has zero knowledge of any programming language or test framework —
that knowledge lives entirely in swappable **adapters**.

## Phases

```
RED           write_test only. run_tests: failing -> VERIFY_RED, already passing -> VERIFY_GREEN.
VERIFY_RED    checkpoint. User confirms the failing test is the right one. verify() -> IMPLEMENT.
IMPLEMENT     write_code only. run_tests: still failing -> stay, passing -> VERIFY_GREEN.
VERIFY_GREEN  checkpoint. User confirms the passing implementation is correct. verify() -> REFACTOR.
REFACTOR      refactor_code only. run_tests: passing -> back to RED (cycle++), failing -> stay + surface error.
```

`RED` normally routes through `IMPLEMENT` (write the test, watch it fail for
the right reason, then write the code that makes it pass) — the same shape as
`SPEC.md`'s `RED`/`GREEN` but with the code-writing step given its own gated
phase, since `write_code` can't be GREEN-only when GREEN is only reachable by
already-passing tests. `VERIFY_RED` and `VERIFY_GREEN` insert an explicit
human checkpoint at the two points where an agent's judgment is easiest to
get wrong unnoticed: right after a test goes red (is this actually testing
the right thing?) and right after it goes green (does this implementation
actually look right, not just pass?). Both are single-tool phases — only
`verify()` (or `get_status()`) is callable — so nothing else can happen until
a human explicitly advances the cycle.

## Architecture

This server is a **gatekeeper**, not a test runner. It holds a phase state
machine in memory and refuses to let Claude call certain tools unless the
phase is right — it never writes code or interprets test output itself. The
actual test-running is delegated to a small external script (an "adapter")
that knows nothing about TDD, phases, or MCP; it just runs a test command and
prints JSON. The split exists so that **swapping languages means writing a
new adapter script, not touching the server** — today it's pytest, tomorrow
it could be `cargo test` or `vitest`, with zero changes to `core/`.

**Why the phase-gating matters.** Without it, an agent doing "TDD" can
quietly skip RED — writing the implementation and a passing test in the same
breath, never observing a real failure, which defeats the point (a test that
never went red might be asserting nothing). Each `write_*` tool raises a
`PhaseError` if called out of turn, surfaced back to Claude as a normal tool
result rather than a crash, so Claude sees "blocked: only allowed in
IMPLEMENT phase" and self-corrects.

**Why `IMPLEMENT` exists.** It's not in the original spec's phase list. The
original design gated `write_code` to GREEN-only, but GREEN was only
reachable once tests already passed — a chicken-and-egg problem: you can't
write the code that makes tests pass if you're not allowed to write code
until they pass. `IMPLEMENT` sits between RED and GREEN to close that gap: a
failing test in RED moves you into VERIFY_RED, then (once verified)
IMPLEMENT, where `write_code` unlocks, and only once tests pass there do you
land in VERIFY_GREEN. VERIFY_GREEN is then a one-tool checkpoint — calling
`verify()` advances unconditionally to REFACTOR, trusting the human has
looked at what's about to be cleaned up.

**A feature is a stack of test targets, not one flat file.** A functional
test rarely gets to GREEN in one leap — it usually needs several unit tests
underneath it, possibly across several apps (`cart/`, `orders/`, ...).
`init_feature` pushes the base level (typically the functional/acceptance
test). `drill_down(testFile)` — only callable in IMPLEMENT — pushes any
other test target on top; it runs its own fully independent
RED→VERIFY_RED→IMPLEMENT→VERIFY_GREEN→REFACTOR cycle, gated exactly like
the base level.
`return_to_parent()` pops back once that nested level finishes a full cycle
(same "RED phase, `cycleCount >= 1`" gate `complete_feature` uses), resuming
the level below exactly where it left off — no phase change, since it was
already sitting in IMPLEMENT waiting. You can drill down as many times, and
as deep, as the feature actually needs; `status()`'s `stack` field shows the
whole chain. There's deliberately no "acceptance"/"unit" label anywhere —
depth alone tells you whether you're at the outer functional test or nested
inside a detour, since a real feature may fan out into any number of test
files across any number of areas of the codebase, not just a fixed two-level
split. `complete_feature` now additionally requires depth 1 — you have to
`return_to_parent` out of every drill-down before the whole feature can be
marked done.

**`return_to_parent` vs `abandon_drill_down`.** Same completed/abandoned
split as `complete_feature`/`reset_feature`, scoped to one level instead of
the whole feature. `return_to_parent` only pops once the nested level
finishes a full cycle (RED, `cycleCount >= 1`) — it means "this drill-down
did its job." `abandon_drill_down` pops unconditionally, from any phase,
with zero cycles required — it means "this drill-down turned out to be
unnecessary," e.g. you drilled into a test file and realized mid-IMPLEMENT
that it wasn't actually needed for the parent to pass. Both resume the
parent level exactly where it was; neither is allowed at depth 1 (the base
level) — `reset_feature` is the equivalent there.

**`write_test` vs `write_test_skeleton`.** Identical enforcement — both are
gated to RED only — the only difference is the name, which exists purely to
carry intent. Note that neither tool actually writes a file or takes test
code as an argument: `write_test(testName)` and `write_test_skeleton(testName)`
both just check the phase (`state_machine.py`); the real file write happens
through Claude's own edit tools outside the MCP protocol entirely — passing
the test body through the MCP call too would just double the tokens spent
on it for no benefit, since nothing here stores or reads it back.
`write_test_skeleton` is opt-in — use it only when
explicitly asked for a skeleton-first workflow (stub test functions with
TODO comments describing the cases to cover, pause for a human to fill in
the TODOs with real detail, then a later `write_test`/`write_test_skeleton`
call fills in the assertions) — otherwise Claude should just call
`write_test` directly, same as before this tool existed.

**Success responses are minimal by design.** `write_test`,
`write_test_skeleton`, `write_code`, and `refactor_code` never mutate
`phase`/`depth`/`testFile`/`cycleCount` — they're pure phase-gate checks — so
on success they return just `{"ok": true}` rather than echoing the full
status back (the caller already has it; nothing changed). Tools that *do*
change state (`init_feature`, `verify`, `run_tests`, `drill_down`,
`return_to_parent`, `abandon_drill_down`, `reset_feature`,
`complete_feature`) still return the full status so the caller can see what
changed. A failed phase check still returns `{"error": "..."}` from any
tool, same as always.

**`reset_feature` vs `complete_feature`.** These sound similar but signal
opposite outcomes. `reset_feature` is phase-unguarded — callable from any
phase, or with no feature active — and exists purely to abandon a feature
(wrong approach, stuck in a broken REFACTOR, whatever). `complete_feature`
only succeeds in RED with `cycleCount >= 1` (i.e. at least one full
RED→VERIFY_RED→IMPLEMENT→VERIFY_GREEN→REFACTOR loop has actually
finished), and its response says so explicitly ("Feature 'x' completed
after N cycle(s)."). Both clear
state identically underneath; the difference is entirely in what got
verified before clearing and what the response tells Claude happened.

**Why the file responsibilities are split this way:**

- `core/state_machine.py` is pure Python with zero I/O and zero MCP
  knowledge — just phase, cycle count, last result, and "you may only call X
  in phase Y." That makes it trivially unit-testable without mocking
  anything (see `tests/test_state_machine.py`) and reusable outside an MCP
  context entirely.
- `core/adapter_contract.py` is the seam between core and language. It shells
  out to whatever adapter path is configured, with a timeout, and validates
  the JSON contract (`passed`, `failed`, `duration_ms`, `failures`,
  `raw_output`) coming back — raising `AdapterError` rather than crashing the
  server if the adapter misbehaves.
- `adapters/pytest-adapter/run.sh` is the only pytest-specific code in the
  whole project. To support a new language, clone this file's shape (same
  CLI contract, same JSON shape out) with entirely different guts inside.
- `core/server.py` is the MCP glue: registers the 12 tools, dispatches each
  `call_tool` into a `TDDStateMachine` method, and for `run_tests`
  specifically also calls the adapter and feeds the result back into the
  state machine. Every response includes the full status (phase, cycle
  count, available tools) so Claude always knows what it's allowed to do
  next without a separate round-trip.
- `.tdd-config.json` (per-consumer-project, not tracked here — only the
  `.example` is) and `.mcp.json` are deliberately two separate files.
  `.tdd-config.json` is the *server's* concern (which adapter, where the
  tests live); `.mcp.json` is *Claude Code's* concern (how to launch the
  process). Keeping them separate means changing test frameworks doesn't
  touch how Claude Code invokes the server, and vice versa.
- `pyproject.toml` packages `core/` as an installable package with the
  `outside-in-tdd-mcp` console-script entry point. This exists because
  `server.py` uses package-relative imports (`from core.adapter_contract
  import ...`), which only resolve if `core` is either installed or the repo
  root is on `sys.path` — a bare `python3 core/server.py` doesn't give you
  that. Packaging it properly means the same install works locally
  (`pip install -e .` then `outside-in-tdd-mcp`) or inside Docker.
- `Dockerfile` is "Option A" from `SPEC.md`: one self-contained image with
  the language runtime baked in (pytest here), simplest to start with. It
  installs the `core` package via `pyproject.toml` and sets
  `ENTRYPOINT ["outside-in-tdd-mcp"]`.

## Layout

```
core/               server.py, state_machine.py, adapter_contract.py — the "core" package
adapters/
  pytest-adapter/    run.sh — the only language-specific piece for pytest
tests/               unit tests for state_machine.py (pytest)
pyproject.toml       packages core/, declares deps, installs the `outside-in-tdd-mcp` console script
Dockerfile           bakes core + pytest adapter + pytest itself into one image
```

## Running the unit tests

```bash
pip install -e .[dev]  # or: pip install pytest
pytest tests/
```

## Installing and running locally (no Docker)

```bash
pip install -e .
outside-in-tdd-mcp   # starts the MCP server on stdio
```

## Building the image

```bash
docker build -t outside-in-tdd-mcp:pytest .
```

## Using in a consumer project

1. Build the image once (from this repo): `docker build -t outside-in-tdd-mcp:pytest .`
2. Copy `.tdd-config.json.example` to `.tdd-config.json` in your project root:
   ```json
   {
     "adapter": "pytest-adapter",
     "adapterPath": "/adapters/pytest-adapter/run.sh",
     "defaultTestDir": "tests/"
   }
   ```
3. Copy `.mcp.json.example` to `.mcp.json` in your project root:
   ```json
   {
     "mcpServers": {
       "outside-in-tdd": {
         "command": "docker",
         "args": ["run", "-i", "--rm", "-v", "${CLAUDE_PROJECT_DIR:-.}:/app", "-w", "/app", "outside-in-tdd-mcp:pytest"]
       }
     }
   }
   ```
   `-v ${CLAUDE_PROJECT_DIR:-.}:/app` is what lets the containerized adapter
   reach the real project's test files and source, mounted at `/app` (which
   matches `adapterPath` above — the adapter script itself lives inside the
   image, not the mount).
4. Open the project in Claude Code / claudecode.nvim — `/mcp` should show
   `outside-in-tdd` as connected, with all 12 tools listed. Claude then calls
   `init_feature` to start a feature, and the phase gating takes over from
   there.

## Adding a new adapter

Write an executable at a known path that:

- takes exactly two CLI args: `<test_target> <project_root>`
- prints exactly one JSON object to stdout:
  `{"passed": N, "failed": N, "duration_ms": N, "failures": [...], "raw_output": "..."}`
- may exit non-zero — the JSON `failed` count is what matters, not the exit code

Then point `.tdd-config.json`'s `adapterPath` at it. Nothing in `core/` needs
to change.

Whatever `failures` an adapter returns, `server.py`'s `run_tests` handler caps
it before it reaches the response or gets stored as `last_result`: at most
20 entries (a 21st summarizing how many were omitted) and 500 characters per
`message`. This is a floor, not a substitute for an adapter capping its own
output — it exists so one large regression check can't balloon a response,
and can't keep re-sending that same balloon on every later `get_status()`.

**`<test_target>` may be more than one bare path.** `init_feature`/`drill_down`
pass `testFile` straight through as `<test_target>`, and Claude may reasonably
send several space-separated targets or a full test-runner argument
expression (e.g. `cart/ order/ -m "not ft"`). Split it with real shell-word
parsing (Python's `shlex.split()`, not naive `str.split(" ")` or an unquoted
bash expansion) — `shlex` correctly keeps a quoted marker expression like
`"not ft"` as one token instead of shredding it on the space inside the
quotes. The pytest adapter (`adapters/pytest-adapter/run.sh`) does exactly
this; use it as the reference shape for a new adapter.

## Getting Claude to actually use this instead of editing files directly

Being connected (`/mcp` shows it) doesn't make Claude prefer these tools
over its own Edit/Write tools — you have to ask. `.claude/commands/` has two
ready-made slash commands (copy them into any consumer project that wants
this workflow — see `.claude/commands/*.md` for the full prompt each one
sends):

- `/tdd-start <feature-name> <test-file>` — starts a feature and walks
  through RED→VERIFY_RED→IMPLEMENT→VERIFY_GREEN→REFACTOR (with drill-downs) using the
  server's tools at each step. Quote the feature name if it has spaces:
  `/tdd-start "checkout discount" tests/functional/test_checkout.py`.
- `/tdd-start-skeleton <feature-name> <test-file>` — same, but RED uses
  `write_test_skeleton` and pauses for you to fill in TODOs before
  continuing.

Both are just prompt templates (`$1`/`$2` filled in from what you type after
the command) — nothing MCP-specific about the mechanism, they just save you
retyping the boilerplate instructions every time. `init_feature`'s `testFile`
has to be an actual file — `write_test` has no `filePath` argument at all
(it's purely a phase checkpoint, same as `write_code`/`refactor_code`), so
if `testFile` were left as a bare directory, Claude would be guessing where
to put the new test with nothing to check its guess against. So both
commands resolve `$1`/`$2` before calling `init_feature`: missing arguments
get asked for outright, and a directory-shaped test target (e.g. `app/`
instead of a specific file) makes Claude inspect how the project's other
apps/modules already lay out their tests and propose a concrete path for
you to confirm, rather than silently inventing one.
