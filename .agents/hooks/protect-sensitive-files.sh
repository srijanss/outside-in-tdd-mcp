#!/usr/bin/env bash
# protect-sensitive-files.sh — PreToolUse → Edit, Write
# Blocks Claude from directly editing secrets, env files, and infra manifests.
# Generic across projects — see lib/protected-patterns.sh.

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/lib/protected-patterns.sh"

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

for pattern in "${EXEMPT_FILE_PATTERNS[@]}"; do
  if echo "$FILE" | grep -qiE "$pattern"; then
    exit 0
  fi
done

for pattern in "${PROTECTED_FILE_PATTERNS[@]}"; do
  if echo "$FILE" | grep -qiE "$pattern"; then
    echo "[protect-files] BLOCKED: '$FILE' is a protected file." >&2
    echo "Edit this file manually — Claude should not touch secrets or infra manifests." >&2
    exit 2
  fi
done

exit 0
