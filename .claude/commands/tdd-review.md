---
description: Check a completed feature or bugfix for missing tests, security issues, bugs, or performance issues (standalone version of the end-of-feature check)
---

This is the standalone version of the check that normally runs at the end
of `/tdd-start` — use it when that step got skipped, or when you want to
re-run it later on something already done.

## Determine scope

Ask me, via `AskUserQuestion`, what to review:
- Uncommitted changes (`git diff` / `git status`)
- The most recent commit (`git show` / `git log -1`)
- Everything since branching from the base branch (e.g. `git diff
  main...HEAD`)
- A specific file or directory I'll name

If `AskUserQuestion` isn't available, ask the same thing as plain text and
wait for my reply. If I pick "a specific file or directory," ask me for the
path before continuing.

## Run the check

Once the scope is settled, read `.claude/docs/tdd-review-checklist.md` and
follow it, scoped to what was determined above (the whole repo only if
that's genuinely what was picked). A chosen finding becomes the next
`/tdd-start` feature — hand it off as the feature name; don't start writing
code in this command.
