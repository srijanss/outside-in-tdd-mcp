# Outside-In TDD MCP Server

A language-agnostic MCP server that enforces Outside-In TDD (RED → IMPLEMENT →
GREEN → REFACTOR) when using Claude Code. The core has zero knowledge of any
programming language or test framework — that knowledge lives entirely in
swappable **adapters**.

## Phases

```
RED        write_test only. run_tests: failing -> IMPLEMENT, already passing -> GREEN.
IMPLEMENT  write_code only. run_tests: still failing -> stay, passing -> GREEN.
GREEN      checkpoint. run_tests advances unconditionally to REFACTOR.
REFACTOR   refactor_code only. run_tests: passing -> back to RED (cycle++), failing -> stay + surface error.
```

`RED` normally routes through `IMPLEMENT` (write the test, watch it fail for
the right reason, then write the code that makes it pass) — the same shape as
`SPEC.md`'s `RED`/`GREEN` but with the code-writing step given its own gated
phase, since `write_code` can't be GREEN-only when GREEN is only reachable by
already-passing tests.

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

1. Copy `.tdd-config.json.example` to `.tdd-config.json` in your project root.
2. Copy `.mcp.json.example` to `.mcp.json` in your project root.
3. Open the project in Claude Code / claudecode.nvim — `/mcp` should show
   `outside-in-tdd` as connected.

## Adding a new adapter

Write an executable at a known path that:

- takes exactly two CLI args: `<test_target> <project_root>`
- prints exactly one JSON object to stdout:
  `{"passed": N, "failed": N, "duration_ms": N, "failures": [...], "raw_output": "..."}`
- may exit non-zero — the JSON `failed` count is what matters, not the exit code

Then point `.tdd-config.json`'s `adapterPath` at it. Nothing in `core/` needs
to change.
