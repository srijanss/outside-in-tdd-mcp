#!/usr/bin/env bash
# PreToolUse hook (Bash matcher): blocks direct test-runner invocations so
# agents go through the outside-in-tdd MCP server's run_tests() tool instead
# — that's the only path that runs tests via the configured adapter and
# advances TDD phase state; a raw pytest/vitest/etc. call bypasses both.
set -euo pipefail

input="$(cat)"
cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty')"

# Boundary: start of string, or right after a shell separator (; & |, which
# also covers && and || since each still contains one of those chars).
# Accept executable paths and the common uv wrapper as well as bare runners.
# This remains a command-text heuristic, not a shell parser or a sandbox.
pattern='(^|[;&|])[[:space:]]*([a-zA-Z_][a-zA-Z0-9_]*=[^[:space:]]+[[:space:]]+)*(([^[:space:];&|]*/)?uv[[:space:]]+run[[:space:]]+(-[^[:space:]]+[[:space:]]+)*)?([^[:space:];&|]*/)?(python([0-9]+(\.[0-9]+)?)?[[:space:]]+-m[[:space:]]+(pytest|unittest)|py\.test|pytest|npx[[:space:]]+vitest|vitest|jest|go[[:space:]]+test|tox|mocha|ava|(npm|yarn|pnpm)[[:space:]]+(run[[:space:]]+)?test)([[:space:]]|$)'

if printf '%s' "$cmd" | grep -Eiq "$pattern"; then
  jq -n '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: "Direct test-runner invocations are blocked in this project — call the outside-in-tdd MCP server'\''s run_tests() tool instead. It runs the suite through the configured adapter (.tdd-config.json) and advances TDD phase state; a raw pytest/vitest/npm test/etc. call bypasses both."
    }
  }'
else
  echo '{}'
fi
