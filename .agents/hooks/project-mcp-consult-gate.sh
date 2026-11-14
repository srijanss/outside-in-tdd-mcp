#!/usr/bin/env bash
# project-mcp consult gate: requires a project-mcp lookup before each gated
# TDD decision point.
#
# Usage: project-mcp-consult-gate.sh mark|check  (hook JSON on stdin)
#
#   mark   PostToolUse on the project-mcp query tools. Drops a marker in this
#          session's scratchpad_dir.
#   check  PreToolUse on the gated tools (outside-in-tdd's init_feature and
#          drill_down: the points where what to build next gets decided;
#          write_test/write_code are left ungated). Denies the call unless the marker
#          exists; on allow it consumes the marker, so each consult unlocks
#          exactly one gated call.
#
# There is no timestamp or TTL: a consult counts until the next gated call
# uses it up. Both modes fail open (allow, write nothing) when scratchpad_dir
# is missing from the hook input, rather than blocking the session forever.
set -euo pipefail

mode="${1:-}"
input="$(cat)"
tool="$(printf '%s' "$input" | jq -r '.tool_name // empty')"
scratchpad_dir="$(printf '%s' "$input" | jq -r '.scratchpad_dir // empty')"

if [ -z "$scratchpad_dir" ]; then
  echo '{}'
  exit 0
fi

marker="$scratchpad_dir/.project-mcp-consulted"

if [ "$mode" = mark ]; then
  mkdir -p "$scratchpad_dir"
  touch "$marker"
  echo '{}'
  exit 0
fi

# Claim the marker with a rename: it is atomic, so when several gated calls
# race for one consult only the process whose mv succeeds is allowed.
claimed="$marker.claimed.$$"
if mv "$marker" "$claimed" 2>/dev/null; then
  rm -f "$claimed"
  echo '{}'
  exit 0
fi

reason="Blocked: call a project-mcp tool relevant to this step (find_symbol,\
 get_symbol_context, get_dependencies, get_dependents or\
 get_project_overview), then retry $tool.\
 Each consult unlocks one init_feature or drill_down call."

jq -n --arg reason "$reason" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: $reason
  }
}'
