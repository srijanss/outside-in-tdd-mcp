#!/usr/bin/env bash
# danger-guard.sh — PreToolUse → Bash
# Blocks destructive commands Claude should never run autonomously, regardless
# of project stack.
#
# NOTE: this is a text-based blocklist over the raw command string. It catches
# the common/obvious forms but is not a sandbox — equivalent effects reached via
# a different program (python -c 'shutil.rmtree(...)', a script piped into bash,
# an alias, etc.) will not be caught. Treat it as a speed bump, not a guarantee.

# Also blocks autonomous git branch creation, and allows commit/push only from
# a linked worktree on a non-main branch (see the git commit/push section).

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/lib/protected-patterns.sh"

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

DANGER_PATTERNS=(
  "DROP TABLE"
  "TRUNCATE TABLE"
  "DELETE FROM"               # bulk deletes (with or without WHERE) — manual only
  "kubectl delete"            # never delete cluster resources autonomously
  "kubectl apply.*production" # never deploy to production autonomously
  "rm -rf"
  "git push[^|;&]*(--force([^-]|$)|--force-with-lease|-f([[:space:]]|$))" # any force push — branch can't be verified from text alone
  "git reset --hard origin"
  # plain git commit / git push: checked below — allowed only in a linked worktree off main
  "git[[:space:]]+checkout[[:space:]]+-b"          # never create a branch autonomously
  "git[[:space:]]+switch[[:space:]]+-c"            # never create a branch autonomously
  "git[[:space:]]+branch[[:space:]]+[^[:space:]-]" # `git branch <name>` creates a branch; -a/-d/--show-current etc. still pass
)

for pattern in "${DANGER_PATTERNS[@]}"; do
  if echo "$CMD" | grep -qiE "$pattern"; then
    echo "[danger-guard] BLOCKED: '$CMD' matches dangerous pattern: '$pattern'" >&2
    echo "Run this manually outside Claude Code if you really need it." >&2
    exit 2
  fi
done

# --- git commit / git push: only from a linked worktree, never on main -------
# Agents work in linked worktrees (git worktree add / .claude/worktrees/...),
# so commit and push are allowed there. In the main checkout, on main/master/
# the remote's default branch, or on a detached HEAD they stay blocked, as does
# any push that targets main explicitly (refspec, --all/--mirror, or an
# upstream that is main). The directory each git command runs in is taken from
# `git -C <dir>`, else the last `cd <dir>` before it, else the hook's cwd.
# Still a text heuristic like everything above — a speed bump, not a sandbox.

HOOK_CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
[ -n "$HOOK_CWD" ] || HOOK_CWD=$PWD

block_git() {
  echo "[danger-guard] BLOCKED: '$CMD' — git $1 is only allowed from a linked worktree on a non-main branch ($2)." >&2
  echo "Work in a worktree (git worktree add ...), or run it manually outside Claude Code." >&2
  exit 2
}

# Resolve a path the agent wrote (quoted, ~, or relative) against a base dir.
resolve_dir() {
  local p=$1 base=$2
  p=${p#\"}; p=${p%\"}; p=${p#\'}; p=${p%\'}
  case "$p" in
    "~") p=$HOME ;;
    "~/"*) p="$HOME/${p#\~/}" ;;
    /*) ;;
    *) p="$base/$p" ;;
  esac
  printf '%s' "$p"
}

# Sets GIT_BRANCH and GIT_DEFAULT on success; sets REASON and returns 1 otherwise.
check_worktree_branch() {
  local d=$1 git_dir common_dir
  [ -d "$d" ] || { REASON="directory '$d' not found"; return 1; }
  git_dir=$(git -C "$d" rev-parse --absolute-git-dir 2>/dev/null) \
    || { REASON="'$d' is not a git repository"; return 1; }
  common_dir=$(cd "$d" && cd "$(git rev-parse --git-common-dir)" && pwd -P)
  git_dir=$(cd "$git_dir" && pwd -P)
  [ "$git_dir" != "$common_dir" ] || { REASON="'$d' is the main checkout, not a linked worktree"; return 1; }
  GIT_BRANCH=$(git -C "$d" symbolic-ref --quiet --short HEAD) \
    || { REASON="detached HEAD"; return 1; }
  GIT_DEFAULT=$(git -C "$d" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null)
  GIT_DEFAULT=${GIT_DEFAULT#*/}
  if is_main_branch "$GIT_BRANCH"; then REASON="branch '$GIT_BRANCH' is a main branch"; return 1; fi
  return 0
}

is_main_branch() {
  case "$1" in
    main | master) return 0 ;;
    "") return 1 ;;
  esac
  [ -n "$GIT_DEFAULT" ] && [ "$1" = "$GIT_DEFAULT" ]
}

GIT_WRITE_RE='(^|[;&|(`[:space:]])git([[:space:]]+-C[[:space:]]+[^[:space:];&|]+)?[[:space:]]+(commit|push)([[:space:]]|$|[;&|)])'
offsets=$(echo "$CMD" | grep -boE "$GIT_WRITE_RE" | cut -d: -f1)
for off in $offsets; do
  rest=${CMD:$off}
  rest=${rest#"${rest%%git*}"}                # drop the leading separator char, if any
  sub=$(echo "$rest" | grep -oE "^git([[:space:]]+-C[[:space:]]+[^[:space:];&|]+)?[[:space:]]+(commit|push)" | grep -oE '(commit|push)$')
  args=$(echo "$rest" | sed -E 's/^git([[:space:]]+-C[[:space:]]+[^[:space:];&|]+)?[[:space:]]+(commit|push)//; s/[;&|].*//')

  dir=$HOOK_CWD
  prefix=${CMD:0:$off}
  cd_arg=$(echo "$prefix" | grep -oE '(^|[;&|(][[:space:]]*)cd[[:space:]]+[^[:space:];&|)]+' | tail -1 | sed -E 's/.*cd[[:space:]]+//')
  [ -n "$cd_arg" ] && dir=$(resolve_dir "$cd_arg" "$HOOK_CWD")
  c_arg=$(echo "$rest" | grep -oE '^git[[:space:]]+-C[[:space:]]+[^[:space:];&|]+' | sed -E 's/^git[[:space:]]+-C[[:space:]]+//')
  [ -n "$c_arg" ] && dir=$(resolve_dir "$c_arg" "$dir")

  check_worktree_branch "$dir" || block_git "$sub" "$REASON"

  if [ "$sub" = push ]; then
    if echo " $args " | grep -qE '[[:space:]]--(all|mirror)([[:space:]]|=)'; then
      block_git push "--all/--mirror pushes every branch, including main"
    fi
    # Explicit refspec destinations: `origin main`, `HEAD:main`, `+x:refs/heads/main`, `:main`.
    for word in $args; do
      case "$word" in -*) continue ;; esac
      dest=${word##*:}; dest=${dest#+}; dest=${dest#refs/heads/}
      is_main_branch "$dest" && block_git push "it targets '$dest'"
    done
    # Bare `git push` / `git push origin`: check where it would actually go.
    nonflag=$(for w in $args; do case "$w" in -*) ;; *) echo "$w" ;; esac; done | wc -l)
    if [ "$nonflag" -le 1 ]; then
      push_to=$(git -C "$dir" rev-parse --abbrev-ref '@{push}' 2>/dev/null)
      [ -n "$push_to" ] && is_main_branch "${push_to#*/}" \
        && block_git push "this branch pushes to '$push_to'"
    fi
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
