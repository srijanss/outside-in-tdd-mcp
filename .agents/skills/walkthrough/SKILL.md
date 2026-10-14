---
name: walkthrough
description: Walk me through the code changes in a git range (e.g. 81b74490...HEAD) so I understand what was built. Defaults to where the current branch started, up to HEAD.
---

Explain the code changes in a git range so the user understands what is
going on. Read-only: do not edit files, commit, or run the project's tests.

## 1. Resolve the range

Range argument given:
- `A...B` or `A..B` — use as-is.
- A single ref `A` — treat as `A..HEAD`.

No argument — "start of the current branch" to HEAD:
1. Find the default branch: `git symbolic-ref --short refs/remotes/origin/HEAD`,
   else the first of `main`, `master`, `trunk` that exists.
2. `base=$(git merge-base <default-branch> HEAD)`; range is `$base..HEAD`.
3. If the current branch *is* the default branch (merge-base == HEAD),
   there is no branch start — don't guess. Tell the user and ask for a
   range (suggest `git log --oneline -20` output to pick from).

State the resolved range and commit count up front. If the range is empty,
say so and stop.

## 2. Gather (cheap first)

- `git log --reverse --format='%h %s' <range>`
- `git diff --stat <range>`
- Then read the full diff per file (`git diff <range> -- <path>`), and
  read surrounding source only where the diff alone isn't enough to
  explain it. Skip lockfiles, generated files and vendored code
  (mention them in one line).

## 3. Explain

Write for someone who has not seen this code. Structure:

1. **What this range does** — 2-4 sentences, the user-visible/behavioral
   goal, not a file list.
2. **How the pieces fit** — the main components and how data/control
   flows between them. Use a small ASCII diagram if it helps.
3. **Walkthrough in logical order** (not alphabetical, and not always
   commit order — dependency/flow order reads best). For each part: what
   it is, why it exists, and the key function/type with `file:line`.
4. **Commit timeline** — one line per commit: what changed and why, if
   the message or diff makes the why clear.
5. **Things worth knowing** — non-obvious decisions, gotchas, TODOs,
   untested or half-finished areas you noticed. Label these as
   observations, not review findings.

Be concrete: quote names and lines, don't paraphrase vaguely. If
something is unclear from the code, say you're inferring rather than
presenting a guess as fact. Finish by offering to go deeper on any one part.
