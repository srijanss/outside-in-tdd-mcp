#!/usr/bin/env bash
# PostToolUse hook (matcher: project-mcp query tools — find_symbol,
# get_symbol_context, get_dependencies, get_dependents, get_project_overview).
# Drops two markers in this session's scratchpad_dir recording that
# project-mcp was consulted:
#
#  - .project-mcp-consulted: stamped with the current epoch time and
#    consumed (deleted) by project-mcp-reminder.sh (PreToolUse on the
#    outside-in-tdd decision-point tools), which requires it no older than
#    its TTL. Re-written fresh on every consult.
#
#  - .project-mcp-session-consulted: a plain existence flag, never deleted
#    once written. project-mcp-session-gate.sh (PreToolUse on Bash/Read)
#    checks only for its presence — once project-mcp has been consulted
#    ONCE this session, cold code exploration is unblocked for the rest of
#    the session. This is deliberately coarser than the TTL marker: it only
#    guards the very first move of a session, not every decision point.
#
# The timestamp is written as file content (epoch seconds) rather than relied
# on via mtime, since stat's mtime flag differs between BSD/macOS and GNU —
# reading file content is portable across both.
set -euo pipefail

input="$(cat)"
scratchpad_dir="$(printf '%s' "$input" | jq -r '.scratchpad_dir // empty')"

if [ -n "$scratchpad_dir" ]; then
  mkdir -p "$scratchpad_dir"
  date +%s > "$scratchpad_dir/.project-mcp-consulted"
  touch "$scratchpad_dir/.project-mcp-session-consulted"
fi

echo '{}'
