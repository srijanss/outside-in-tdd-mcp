# Outside-In TDD MCP Server — Project Spec

## Goal

Build a **language-agnostic MCP server** that enforces Outside-In TDD (RED → GREEN → REFACTOR) when using Claude Code. The core has zero knowledge of any programming language or test framework — that knowledge lives in small, swappable **adapters**.

Use case: Currently building for Django (pytest), but designed so any future project (Rust, Go, JS, TS) can plug in without touching the core.

---

## Architecture

```
outside-in-tdd-mcp-base/              ← Built once, reused everywhere
├── server.py                         ← MCP protocol handler (stdio transport)
├── state_machine.py                  ← Phase logic: RED/GREEN/REFACTOR + acceptance→unit drill-down
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

1. **Core tracks acceptance vs. unit test distinction.** The adapter doesn't know or care what kind of test it's running — it just runs whatever file/target path it's given and returns results. The state machine in `state_machine.py` tracks whether the current test file is an acceptance test or a unit test.

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
RED       → Write/run a failing test
GREEN     → Write code to make it pass
REFACTOR  → Clean up code, tests must stay green
```

### Feature Lifecycle

```
init_feature(name, testFile)
  → Phase: RED

write_test(name, code)
  → Only allowed in RED
  → Blocks with error if called in GREEN or REFACTOR

run_tests()
  → Calls adapter, gets JSON result
  → If RED and failures > 0: stay in RED
  → If RED and failures == 0 and passed > 0: advance to GREEN
  → If GREEN: advance to REFACTOR (assumes you're now ready to clean)
  → If REFACTOR and tests still pass: advance back to RED, increment cycle count
  → If REFACTOR and tests fail: something broke during refactor, stay in REFACTOR, surface error

write_code(filePath, code)
  → Only allowed in GREEN
  → Blocks with error if called in RED or REFACTOR

refactor_code(description)
  → Only allowed in REFACTOR
  → Blocks with error if called in RED or GREEN

get_status()
  → Returns: current feature, phase, cycle count, last test results, available tools

reset_feature()
  → Clears current feature state, ready for init_feature() on a new feature
```

### Tool Availability By Phase

```
RED:      write_test, run_tests, get_status, init_feature
GREEN:    write_code, run_tests, get_status
REFACTOR: refactor_code, run_tests, get_status
```

---

## MCP Tool Definitions (for server.py)

```python
TOOLS = [
    {
        "name": "init_feature",
        "description": "Start a new TDD feature. Sets phase to RED.",
        "input_schema": {
            "type": "object",
            "properties": {
                "featureName": {"type": "string"},
                "testFile": {"type": "string", "description": "Path relative to project root"}
            },
            "required": ["featureName", "testFile"]
        }
    },
    {
        "name": "write_test",
        "description": "Write a failing test. Only available in RED phase.",
        "input_schema": {
            "type": "object",
            "properties": {
                "testName": {"type": "string"},
                "code": {"type": "string"}
            },
            "required": ["testName", "code"]
        }
    },
    {
        "name": "write_code",
        "description": "Write implementation code. Only available in GREEN phase.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filePath": {"type": "string"},
                "code": {"type": "string"}
            },
            "required": ["filePath", "code"]
        }
    },
    {
        "name": "run_tests",
        "description": "Run the test suite via the configured adapter. Auto-advances phase based on results.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "refactor_code",
        "description": "Refactor code. Only available in REFACTOR phase.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string"}
            },
            "required": ["description"]
        }
    },
    {
        "name": "get_status",
        "description": "Get current feature, phase, test results, and available tools.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "reset_feature",
        "description": "Reset current feature. Allows starting a new one.",
        "input_schema": {"type": "object", "properties": {}}
    }
]
```

---

## Example: pytest Adapter

```bash
#!/bin/bash
# adapters/pytest-adapter/run.sh
set -e

TEST_TARGET=$1
PROJECT_ROOT=$2

cd "$PROJECT_ROOT"

pytest "$TEST_TARGET" -v --tb=short --json-report --json-report-file=/tmp/tdd-report.json > /tmp/tdd-raw-output.txt 2>&1 || true

python3 <<EOF
import json

with open('/tmp/tdd-report.json') as f:
    report = json.load(f)

with open('/tmp/tdd-raw-output.txt') as f:
    raw_output = f.read()

failures = []
for test in report.get('tests', []):
    if test['outcome'] == 'failed':
        failures.append({
            'name': test['nodeid'],
            'message': str(test.get('call', {}).get('longrepr', ''))[:500]
        })

result = {
    'passed': report['summary'].get('passed', 0),
    'failed': report['summary'].get('failed', 0),
    'duration_ms': int(report.get('duration', 0) * 1000),
    'failures': failures,
    'raw_output': raw_output[-3000:]  # last 3000 chars to avoid huge output
}

print(json.dumps(result))
EOF
```

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
assert sm.phase == "red"  # still red
sm.record_test_result(passed=1, failed=0)
assert sm.phase == "green"  # advanced
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
- [ ] Full cycle works manually: `init_feature` → `write_test` → `run_tests` (fails, stays RED) → `write_code` → `run_tests` (passes, advances GREEN) → `refactor_code` → `run_tests` (passes, advances back to RED)
- [ ] Server correctly **blocks** `write_code` when called during RED phase
- [ ] Server correctly **blocks** `write_test` when called during GREEN phase
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

---

## Key Principle to Hold Onto

**If you ever find yourself writing language-specific logic (parsing pytest output, checking for `def test_`, anything Python-test-specific) inside `state_machine.py` or `server.py` — stop.** That logic belongs in the adapter. The core's job is only: track phase, decide what's allowed, call the adapter, interpret pass/fail counts. Nothing more.
