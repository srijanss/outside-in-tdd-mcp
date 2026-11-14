---
name: tdd-backfill-features
description: Backfill .tdd-features.json statuses from git history, scoped to a given starting commit — not a full repo scan
---

You have been given a since-ref (a commit SHA, tag, or ref like `HEAD~15` —
the point to start reading git history from) and optionally a plan file
path (defaults to `.tdd-features.json`).

## Resolving the since-ref

Never scan the whole repo history — that's the thing this skill exists to
avoid. If the since-ref is missing, don't guess it — read the plan file's
existing entries first (via `list_features()`, or reading the file directly
if the MCP server isn't configured for this project) and find the newest
`recordedAt` timestamp already present. Propose the commit closest to that
timestamp (`git log --since=<that date> --oneline | tail -1`, or similar)
as a candidate since-ref, and ask for confirmation or a different one
before proceeding. If the plan file has no `recordedAt` values yet (nothing
has ever run through the state machine), ask directly for a since-ref.

## Gathering evidence, scoped only to the given range

Once since-ref is settled:

1. Read the plan file's entries. Only entries with `status` of `"pending"`
   or `"in_progress"` are candidates for backfilling — never touch entries
   already `"completed"` or `"abandoned"`.
2. Run `git log --oneline <since-ref>..HEAD` — scoped strictly to that
   range, not the full log. If more detail is needed on a specific commit
   (full message, diff), fetch that one commit individually
   (`git show <sha>`) rather than requesting full diffs for the whole range
   up front.
3. For each candidate entry, look for a commit in that range whose message
   or diff clearly implements it (match on `featureName`/`description`,
   and — if the entry already has `testFile`/`targetFiles` from a prior
   partial run — check those specific paths). Also check current repo state:
   do the relevant test file(s) exist and pass? A feature can only be
   "done" if its test target actually exists and is green — a commit
   message alone isn't enough evidence.

## Applying updates — conservative by default

- Mark an entry `"completed"` only when a specific commit was found *and*
  its test currently passes was confirmed. Record that commit as
  `"backfilledFrom": "<sha>"` on the entry (a marker distinct from a normal
  `complete_feature()` run — this wasn't verified live through the state
  machine's own RED→GREEN→REFACTOR cycle, so don't hide that it was
  inferred). Fill in `testFile`/`targetFiles` if identifiable and not
  already set; leave `cyclesCompleted` as `null` if unknown rather than
  guessing a number.
- If evidence is ambiguous — a plausible commit but the description doesn't
  clearly match, or the test target doesn't exist/doesn't pass — do NOT
  mark it completed. List it separately as "unclear" for a human to decide.
- Edit the plan file directly (it's a JSON array on disk) to apply
  approved updates — don't call `complete_feature()` for these, since that
  requires an active in-memory cycle this skill never drives. Preserve
  every entry's existing `description`/`dependsOn` untouched.

## Report back

End with a short summary: which features were marked `"completed"` (with
their commit SHA), and which were left as-is because the evidence was
unclear, so those can be resolved manually.
