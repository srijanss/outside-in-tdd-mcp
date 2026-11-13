#!/usr/bin/env bash
# PreToolUse hook (matcher: Bash, Read). Blocks cold source-code exploration
# — grep/rg/ag/find/cat over the codebase, or Read of a source file — until
# project-mcp has been consulted at least once this session.
#
# Why this exists: the TTL-gated hooks (project-mcp-reminder.sh /
# project-mcp-mark-consulted.sh) only fire on outside-in-tdd's TDD
# decision-point tools (init_feature, write_test, write_code, ...). Nothing
# stopped Claude from reaching for Bash(ls/grep/find) or Read to explore the
# codebase cold at the very start of a session, before any TDD tool — and in
# practice it did exactly that. This hook closes that gap.
#
# Deliberately coarse compared to the TTL gate: it only checks whether
# project-mcp has EVER been consulted this session (see
# .project-mcp-session-consulted, written once and never deleted by
# project-mcp-mark-consulted.sh), not whether the consult was fresh for this
# specific step. Once you've made one project-mcp call, exploration is
# unrestricted for the rest of the session — the goal is just to stop the
# "start cold with grep" pattern, not to gate every Read/Bash call forever.
#
# Classification is necessarily a heuristic since PreToolUse matchers can't
# filter by command text or file path — only by tool name. So this script
# parses tool_input itself:
#   - Bash: gated only if the command contains grep, rg, ag, find, or cat as
#     a whole word (i.e. actually invokes one of those tools, not just
#     mentions the word). Plain `ls`, git commands, test runs, etc. pass
#     through ungated — those aren't the cold-exploration pattern this
#     guards against.
#   - Read: gated for supported source file extensions. Config and docs
#     reads pass through.
set -euo pipefail

input="$(cat)"
tool="$(printf '%s' "$input" | jq -r '.tool_name // empty')"
scratchpad_dir="$(printf '%s' "$input" | jq -r '.scratchpad_dir // empty')"

allow() {
  echo '{}'
  exit 0
}

# Fail open if we can't locate the session scratchpad — same policy as the
# TTL gate.
if [ -z "$scratchpad_dir" ]; then
  allow
fi

session_marker="$scratchpad_dir/.project-mcp-session-consulted"
if [ -f "$session_marker" ]; then
  allow
fi

is_gated=false

case "$tool" in
  Bash)
    command_text="$(printf '%s' "$input" | jq -r '.tool_input.command // empty')"
    if printf '%s' "$command_text" | grep -qE '(^|[^a-zA-Z0-9_])(grep|rg|ag|find|cat)([^a-zA-Z0-9_]|$)'; then
      is_gated=true
    fi
    ;;
  Read)
    file_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')"
    case "$file_path" in
      *.py|*.pyi|*.js|*.jsx|*.ts|*.tsx|*.rs|*.astro) is_gated=true ;;
    esac
    ;;
esac

if [ "$is_gated" != true ]; then
  allow
fi

reason=$(printf '%s' \
  "Blocked: this looks like cold source-code exploration. Call a " \
  "project-mcp tool (get_project_overview, find_symbol, " \
  "get_context_for_feature, etc.) first to get structured project context " \
  "instead of grepping/reading blind. This only gates the first move of a " \
  "session — once you've made one project-mcp call, this hook stops " \
  "blocking for the rest of the session.")

jq -n --arg reason "$reason" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: $reason
  }
}'
