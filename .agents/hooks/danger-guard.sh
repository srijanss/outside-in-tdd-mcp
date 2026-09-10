#!/usr/bin/env bash
# danger-guard.sh — PreToolUse → Bash
# Blocks destructive commands Claude should never run autonomously, regardless
# of project stack.
#
# NOTE: this is a text-based blocklist over the raw command string. It catches
# the common/obvious forms but is not a sandbox — equivalent effects reached via
# a different program (python -c 'shutil.rmtree(...)', a script piped into bash,
# an alias, etc.) will not be caught. Treat it as a speed bump, not a guarantee.

# Also blocks any autonomous git branch creation, commit, or push — those
# always require explicit user consent per standing instruction.

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/lib/protected-patterns.sh"

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

DANGER_PATTERNS=(
  "DROP TABLE"
  "TRUNCATE TABLE"
  "DELETE FROM"                             # bulk deletes (with or without WHERE) — manual only
  "kubectl delete"                          # never delete cluster resources autonomously
  "kubectl apply.*production"               # never deploy to production autonomously
  "rm -rf"
  "git push[^|;&]*(--force([^-]|$)|--force-with-lease|-f([[:space:]]|$))"  # any force push — branch can't be verified from text alone
  "git reset --hard origin"
  "^[[:space:]]*git[[:space:]]+commit"      # never commit autonomously — user commits, always
  "git[[:space:]]+push"                     # never push autonomously, force or not
  "git[[:space:]]+checkout[[:space:]]+-b"   # never create a branch autonomously
  "git[[:space:]]+switch[[:space:]]+-c"     # never create a branch autonomously
  "git[[:space:]]+branch[[:space:]]+[^[:space:]-]"  # `git branch <name>` creates a branch; -a/-d/--show-current etc. still pass
)

for pattern in "${DANGER_PATTERNS[@]}"; do
  if echo "$CMD" | grep -qiE "$pattern"; then
    echo "[danger-guard] BLOCKED: '$CMD' matches dangerous pattern: '$pattern'" >&2
    echo "Run this manually outside Claude Code if you really need it." >&2
    exit 2
  fi
done

# Block Bash from writing to protected files (secrets, env files, infra
# manifests) the same way protect-sensitive-files.sh blocks Edit/Write — e.g.
# `cat > .env`, `sed -i ... k8s/deploy.yaml`, `cp foo id_rsa.key`, `tee secrets.yaml`.
WRITE_OP_REGEX='(>>?[^&]|(^|[[:space:]])(cp|mv|tee|sed[[:space:]]+\-i|dd)[[:space:]])'
if echo "$CMD" | grep -qE "$WRITE_OP_REGEX"; then
  EXEMPT=false
  for pattern in "${EXEMPT_FILE_PATTERNS[@]}"; do
    if echo "$CMD" | grep -qiE "$pattern"; then
      EXEMPT=true
      break
    fi
  done

  if [ "$EXEMPT" = false ]; then
    for pattern in "${PROTECTED_FILE_PATTERNS_LOOSE[@]}"; do
      if echo "$CMD" | grep -qiE "$pattern"; then
        echo "[danger-guard] BLOCKED: '$CMD' looks like a write to a protected file (matches: '$pattern')" >&2
        echo "Edit this file manually — Claude should not touch secrets or infra manifests." >&2
        exit 2
      fi
    done
  fi
fi

exit 0
