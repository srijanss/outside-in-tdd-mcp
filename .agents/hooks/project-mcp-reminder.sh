#!/usr/bin/env bash
# PreToolUse hook (matcher: outside-in-tdd MCP tools that start a TDD
# decision point — init_feature, drill_down, write_test, write_test_skeleton,
# write_code). Enforces that a project-mcp tool (find_symbol,
# get_symbol_context, get_dependencies, get_dependents, get_project_overview)
# was called *recently* (within MARKER_TTL_SECONDS) before this decision
# point, and blocks the call otherwise.
#
# refactor_code is deliberately NOT gated: it always follows write_code
# within the same cycle (RED -> ... -> IMPLEMENT (write_code, gated) ->
# VERIFY_GREEN -> REFACTOR (refactor_code)), so a fresh consult already
# happened for this cycle's actual change. Gating it too only produced
# no-op "no refactor needed" consults that didn't inform anything.
#
# Why this exists: a soft additionalContext reminder alone was observed to
# be followed only once per session (the first research pass), not before
# every decision point, even though the reminder fired every time. See
# project-mcp-mark-consulted.sh (PostToolUse on the project-mcp tools) for
# the other half of this — it drops the timestamped marker this script looks
# for.
#
# The marker is TTL-checked (not just presence-checked) because an
# unconsumed marker from an earlier, unrelated consult — e.g. left over from
# before a /clear, which resets conversation context but not files on disk —
# would otherwise silently satisfy this gate for a decision it was never
# actually consulted for. A short TTL means only a consult made for *this*
# decision (moments ago) counts; a stale one is treated the same as absent.
#
# The marker lives in this session's scratchpad_dir (given in the hook
# input), so it's scoped per-session and doesn't collide across concurrent
# sessions. If scratchpad_dir isn't available for some reason, this fails
# open (allows the call) rather than permanently blocking the session.
set -euo pipefail

MARKER_TTL_SECONDS=120

input="$(cat)"
tool="$(printf '%s' "$input" | jq -r '.tool_name // empty')"
scratchpad_dir="$(printf '%s' "$input" | jq -r '.scratchpad_dir // empty')"

if [ -z "$scratchpad_dir" ]; then
  echo '{}'
  exit 0
fi

marker="$scratchpad_dir/.project-mcp-consulted"
now="$(date +%s)"
marker_time="$( [ -f "$marker" ] && cat "$marker" 2>/dev/null || echo "" )"

deny() {
  jq -n --arg tool "$tool" --arg reason "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
}

stale_or_missing_reason() {
  printf '%s' \
    "Blocked: call a project-mcp tool (find_symbol, get_symbol_context, " \
    "get_dependencies, get_dependents, or get_project_overview) relevant " \
    "to this step, then retry $1. This is a standing requirement for this " \
    "project — check existing project structure, symbols, and " \
    "dependencies before deciding what to test or implement, instead of " \
    "guessing or grepping from scratch. A consult older than " \
    "${MARKER_TTL_SECONDS}s doesn't count — it must be fresh for this " \
    "decision, not left over from earlier work."
}

if [ -z "$marker_time" ] || ! [[ "$marker_time" =~ ^[0-9]+$ ]]; then
  rm -f "$marker"
  deny "$(stale_or_missing_reason "$tool")"
  exit 0
fi

age=$(( now - marker_time ))
if [ "$age" -gt "$MARKER_TTL_SECONDS" ]; then
  rm -f "$marker"
  deny "$(stale_or_missing_reason "$tool")"
else
  rm -f "$marker"
  echo '{}'
fi
