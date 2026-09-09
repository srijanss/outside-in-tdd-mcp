# Outside-In TDD MCP Server — Project Spec

> **Status:** this is the original design doc. The phases, tool list, and
> adapter example below have been updated to match what's actually built —
> for anything not covered here (drill-down rationale, the human verify
> checkpoints, per-tool details), `README.md` is the up-to-date reference.

## Goal

Build a **language-agnostic MCP server** that enforces Outside-In TDD (RED → VERIFY_RED → IMPLEMENT → VERIFY_GREEN → REFACTOR) when using Claude Code. The core has zero knowledge of any programming language or test framework — that knowledge lives in small, swappable **adapters**.

Use case: Currently building for Django (pytest), but designed so any future project (Rust, Go, JS, TS) can plug in without touching the core.

---

## Architecture

```
outside-in-tdd-mcp-base/              ← Built once, reused everywhere
├── server.py                         ← MCP protocol handler (stdio transport)
├── state_machine.py                  ← Phase logic: RED/VERIFY_RED/IMPLEMENT/VERIFY_GREEN/REFACTOR + depth-based drill-down
├── adapter_contract.py               ← Defines the interface every adapter must satisfy
├── Dockerfile                        ← Zero language runtimes, just Python for the MCP server itself
└── requirements-core.txt             ← Only MCP SDK + minimal deps

adapters/                             ← One per language/test framework
├── pytest-adapter/
│   └── run.sh                        ← Runs pytest, outputs contract-shaped JSON
├── vitest-adapter/                     ← (future)
├── cargo-test-adapter/               ← (future)
└── go-test-adapter/                  ← (future)

your-django-project/                  ← Example consumer project
├── .mcp.json                         ← Tells Claude Code how to launch the server
├── .tdd-config.json                  ← Tells the server which adapter to use
└── (your actual Django code)
```

---

## Core Design Decisions (Already Made)

1. **Core tracks depth, not an acceptance/unit label.** The adapter doesn't know or care what kind of test it's running — it just runs whatever file/target path it's given and returns results. A feature is a *stack* of test-target levels: `init_feature` pushes the base level, `drill_down` pushes any nested test target needed along the way (a unit test, a different app, anything), each running its own independent phase cycle. There's no "acceptance"/"unit" label anywhere — depth in the stack is the only signal, since a feature may fan out into any number of test files across any number of areas of the codebase.

2. **Config is split into two files:**
   - `.mcp.json` — Claude Code's concern: how to launch the server (command, args, volume mounts)
   - `.tdd-config.json` — The server's own concern: which adapter to use, test command, default test directory

3. **Adapter discovery is hardcoded path for v1** (e.g., `/adapters/pytest-adapter/run.sh`), referenced by name in `.tdd-config.json`. Convention-based auto-discovery (`.tdd-adapters/<name>/run.sh`) is a v2 nice-to-have, not needed now.

---

## The Adapter Contract (The Only Language-Specific Seam)

This is the entire interface between the core and any language. Any adapter — in any language — must satisfy this:

### Input (adapter receives via CLI args)

```bash
./run.sh <test_target> <project_root>
# Example: ./run.sh tests/test_validators.py /app
```

### Output (adapter must print exactly one JSON object to stdout)

```json
{
  "passed": 3,
  "failed": 1,
  "duration_ms": 452,
  "failures": [
    {
      "name": "test_blacklist_check",
      "message": "AssertionError: expected False, got True"
    }
  ],
  "raw_output": "... full test runner output for debugging ..."
}
```

**Rules for any adapter:**

- Must be an executable script (bash, python, whatever) at a known path
- Takes exactly 2 positional args: test target path, project root
- Prints exactly one JSON object to stdout matching the shape above
- Non-zero exit code is fine (tests failing isn't a script error) — the JSON `failed` count is what matters
- Everything language/framework-specific (parsing pytest output vs. cargo output vs. vitest output) lives entirely inside the adapter script

---

## State Machine Specification

### Phases

```
RED           → Write/run a failing test
VERIFY_RED    → Checkpoint: a human confirms the failing test is the right one
IMPLEMENT     → Write code to make it pass
VERIFY_GREEN  → Checkpoint: a human confirms the passing implementation looks right
REFACTOR      → Clean up code, tests must stay green
```

`VERIFY_RED` and `VERIFY_GREEN` aren't in the original 3-phase list above —
see README.md for why they exist: they're single-tool phases (only
`verify()`/`get_status()` are callable) so an agent can't self-approve past
the two points where its judgment is easiest to get wrong unnoticed.

### Feature Lifecycle

```
init_feature(name, testFile, targetFiles)
  → Phase: RED
  → targetFiles must be [] — the base level never owns implementation
    files directly (regardless of whether testFile is acceptance, unit, or
    a refactor-only feature). Rejected with InvalidTargetFilesError if
    non-empty. Real implementation file(s) are declared later via
    drill_down() (see write_code below).
  → If name matches a .tdd-features.json entry: blocks with an error if
    that entry's status is already "completed" or "in_progress", or if
    any of its dependsOn features aren't "completed" yet. Otherwise flips
    the entry's status to "in_progress". A name not in the ledger starts
    normally (ad hoc, no plan/dependency checks).

write_test(name)
  → Only allowed in RED
  → Blocks with error otherwise

run_tests()
  → Calls adapter, gets JSON result
  → If RED and failures > 0: advance to VERIFY_RED
  → If RED and failures == 0 and passed > 0: advance to VERIFY_GREEN (nothing needed implementing)
  → If IMPLEMENT and failures > 0: stay in IMPLEMENT
  → If IMPLEMENT and failures == 0 and passed > 0: advance to VERIFY_GREEN
  → If REFACTOR and tests still pass: advance back to RED, increment cycle count
  → If REFACTOR and tests fail: something broke during refactor, stay in REFACTOR, surface error

verify()
  → Only allowed in VERIFY_RED or VERIFY_GREEN
  → VERIFY_RED → IMPLEMENT; VERIFY_GREEN → REFACTOR
  → No auto-approval path — a human (via the calling agent) must call this

write_code(filePath)
  → Only allowed in IMPLEMENT
  → Blocks with error otherwise
  → filePath must be one of the current level's declared targetFiles
    (set by init_feature/drill_down) — new or existing file. A filePath
    outside that set is blocked: that content needs its own test first,
    via drill_down(), not direct implementation.

refactor_code(description)
  → Only allowed in REFACTOR
  → Blocks with error otherwise

get_status()
  → Returns: current feature, depth, phase, cycle count, last test results, available tools

reset_feature()
  → Discards the current feature from any phase/depth, ready for init_feature() on a new one
  → Sets its .tdd-features.json entry's status to "abandoned" (upserted —
    updates the plan entry in place if one exists, else appends a new one)

complete_feature()
  → Only allowed at depth 1, in RED, after cycleCount >= 1
  → Clears feature state and reports success (distinct from reset_feature's abandonment)
  → Sets its .tdd-features.json entry's status to "completed" (same
    upsert as reset_feature), unblocking any features whose dependsOn
    lists it

list_features()
  → Returns the full contents of .tdd-features.json: an optional upfront
    plan (featureName, description, dependsOn) with status/testFile/
    targetFiles/cyclesCompleted/recordedAt kept up to date by
    init_feature/complete_feature/reset_feature as work progresses
    ("pending" → "in_progress" → "completed"/"abandoned") — independent
    of the current in-memory feature/phase. See "Feature Plan Ledger"
    below for the file's schema.

drill_down(testFile, targetFiles)
  → Only allowed in IMPLEMENT — pushes a nested test target with its own independent cycle
  → targetFiles declares the implementation file(s) this nested level
    owns, same rule write_code() enforces at every level

return_to_parent()
  → Only allowed in RED after the current (nested) level finishes a full cycle — pops back to the parent

abandon_drill_down()
  → Unconditionally pops the current nested level, any phase, any cycle count — for a drill-down that turned out unnecessary
```

### Feature Plan Ledger (.tdd-features.json)

Optional. Write it yourself (before any init_feature calls) as a JSON
array, broken down into the smallest features you can, e.g.:

```json
[
  { "featureName": "user-model", "description": "...", "dependsOn": [], "status": "pending" },
  { "featureName": "auth-login", "description": "...", "dependsOn": ["user-model"], "status": "pending" }
]
```

`dependsOn` names other entries' `featureName` values. `status` starts
`"pending"`; the server flips it to `"in_progress"` on init_feature (after
checking every `dependsOn` entry is `"completed"` — see init_feature
above), and to `"completed"`/`"abandoned"` on complete_feature/
reset_feature, filling in `testFile`, `targetFiles`, `cyclesCompleted`,
and `recordedAt` at the same time. A feature started via init_feature with
a name not already in the file gets appended automatically, with no
dependency checks — the plan is optional, not required to use the server.

### Tool Availability By Phase

```
RED:           write_test, run_tests, get_status, init_feature
VERIFY_RED:    verify, get_status
IMPLEMENT:     write_code, run_tests, get_status
VERIFY_GREEN:  verify, get_status
REFACTOR:      refactor_code, run_tests, get_status
```

---

## MCP Tool Definitions (for server.py)

The full `TOOLS` list (with exact descriptions and input schemas) lives in
`core/server.py` — duplicating it here just goes stale, as this section
already did once. Current tool names: `init_feature`, `write_test`,
`write_test_skeleton`, `write_code`, `verify`, `run_tests`,
`refactor_code`, `get_status`, `list_features`, `reset_feature`,
`complete_feature`, `drill_down`, `return_to_parent`, `abandon_drill_down`,
`record_research`, `list_research`.
See the "State Machine Specification" section above for what each does and
when it's allowed.

---

## Example: pytest Adapter

The real, current implementation is `adapters/pytest-adapter/run.sh` — it's
grown real edge-case handling since this doc was first written (a
collection-time error, like a bad import or syntax error, has to be
distinguished from a per-test fixture setup/teardown error and from a
benign "no tests collected" result — pytest and `pytest-json-report`
signal these differently, and getting this wrong means a real RED failure
gets silently reported as `passed=0, failed=0`), so it's no longer
reproduced here. Read that file directly; the shape it must satisfy is
unchanged — see "The Adapter Contract" above.

**Requires:** `pip install pytest-json-report` in whatever environment runs this (Docker image or mounted venv).

---

## `.tdd-config.json` (Lives in Consumer Project)

```json
{
  "adapter": "pytest-adapter",
  "adapterPath": "/adapters/pytest-adapter/run.sh",
  "defaultTestDir": "tests/"
}
```

---

## `.mcp.json` (Lives in Consumer Project, for Claude Code / claudecode.nvim)

### Option A: Fully Dockerized (core + adapter + language runtime baked into one image)

```json
{
  "mcpServers": {
    "outside-in-tdd": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-v",
        "${CLAUDE_PROJECT_DIR:-.}:/app",
        "-w",
        "/app",
        "outside-in-tdd-mcp:pytest"
      ]
    }
  }
}
```

### Option B: Core in Docker, mounts project's own venv/toolchain (recommended to start)

```json
{
  "mcpServers": {
    "outside-in-tdd": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-v",
        "${CLAUDE_PROJECT_DIR:-.}:/app",
        "-v",
        "${CLAUDE_PROJECT_DIR:-.}/.venv:/app/.venv",
        "-w",
        "/app",
        "outside-in-tdd-mcp:core"
      ]
    }
  }
}
```

**Recommendation: Start with Option A for simplicity** (one image per language, includes runtime + adapter). Move to Option B once you have 2+ languages and want to stop rebuilding images for every project.

---

## Build Order (Do This Step-By-Step)

### Step 1: Core state machine (no I/O, pure logic)

Build `state_machine.py` as a standalone class with no MCP or subprocess code. Fully unit-testable in isolation:

```python
sm = TDDStateMachine()
sm.init_feature("test feature", "tests/test_x.py")
assert sm.phase == "red"
sm.record_test_result(passed=0, failed=1)
assert sm.phase == "verify_red"  # advanced — a human confirms before IMPLEMENT unlocks
sm.verify()
assert sm.phase == "implement"
sm.record_test_result(passed=1, failed=0)
assert sm.phase == "verify_green"  # advanced
```

### Step 2: Adapter contract + pytest adapter

Write `pytest-adapter/run.sh`. Test it standalone from the command line against a real Django test file — no MCP involved yet:

```bash
./adapters/pytest-adapter/run.sh tests/test_validators.py /path/to/django/project
# Should print the JSON contract shape
```

### Step 3: Wire server.py (MCP protocol + calls state_machine + calls adapter)

This is the glue layer. Handles:

- MCP tool registration (the TOOLS list above)
- Tool call dispatch → state_machine methods
- `run_tests()` specifically shells out to the adapter script, parses its JSON, feeds it into `state_machine.record_test_result()`

### Step 4: Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /mcp
RUN pip install mcp pytest pytest-json-report django
COPY server.py state_machine.py adapter_contract.py /mcp/
COPY adapters/pytest-adapter/run.sh /adapters/pytest-adapter/run.sh
RUN chmod +x /adapters/pytest-adapter/run.sh
ENTRYPOINT ["python", "server.py"]
```

### Step 5: `.mcp.json` in your actual Django project

Point it at the built image (Option A above).

### Step 6: Test end-to-end with Claude Code / claudecode.nvim

```bash
docker build -t outside-in-tdd-mcp:pytest .
# In your Django project, with .mcp.json in place:
# Open nvim → claudecode.nvim launches claude → /mcp shows outside-in-tdd connected
```

---

## Directory Structure to Create in nvim Project

```
outside-in-tdd-mcp/
├── core/
│   ├── server.py
│   ├── state_machine.py
│   └── adapter_contract.py
├── adapters/
│   └── pytest-adapter/
│       └── run.sh
├── Dockerfile
├── requirements-core.txt
├── .tdd-config.json.example
├── .mcp.json.example
└── README.md
```

---

## Testing Checklist (Definition of Done for V1)

- [ ] `state_machine.py` has unit tests covering every phase transition, run standalone with pytest (meta, testing the tester)
- [ ] `pytest-adapter/run.sh` runs standalone against a real test file, outputs valid contract JSON
- [ ] `server.py` starts and responds to `get_tools` MCP call
- [ ] Full cycle works manually: `init_feature` → `write_test` → `run_tests` (fails, advances to VERIFY_RED) → `verify` → `write_code` → `run_tests` (passes, advances to VERIFY_GREEN) → `verify` → `refactor_code` → `run_tests` (passes, advances back to RED)
- [ ] Server correctly **blocks** `write_code` when called during RED phase
- [ ] Server correctly **blocks** `write_test` when called during IMPLEMENT phase
- [ ] Server correctly **blocks** `verify` when called outside VERIFY_RED/VERIFY_GREEN (an agent can't self-approve past the checkpoint)
- [ ] `.mcp.json` successfully launches the server from claudecode.nvim
- [ ] `/mcp` in Claude Code shows `outside-in-tdd` as connected
- [ ] Full real feature (payment email validation or similar) built end-to-end through Claude using only these MCP tools

---

## Future Extensions (Not V1, Just Noted)

- Coverage tracking (adapter returns coverage % alongside pass/fail)
- Slow test detection (adapter already returns duration_ms — just needs a threshold check in state_machine)
- Git commit hooks at phase transitions
- Session logging to a `.tdd-session.log` for cross-session review
- Convention-based adapter discovery instead of hardcoded path
- Additional adapters: vitest, cargo test, go test
- Cost management: avoid redundant `run_tests()`/adapter invocations (e.g.
  cache results for an unchanged test target) and trim what's echoed back
  to Claude on each MCP call

---

## Key Principle to Hold Onto

**If you ever find yourself writing language-specific logic (parsing pytest output, checking for `def test_`, anything Python-test-specific) inside `state_machine.py` or `server.py` — stop.** That logic belongs in the adapter. The core's job is only: track phase, decide what's allowed, call the adapter, interpret pass/fail counts. Nothing more.
