---
description: Backfill .tdd-features.json statuses from git history, scoped to a given starting commit — not a full repo scan
argument-hint: <since-ref> [plan-file]
---

Arguments: since ref = "$1" (a commit SHA, tag, or ref like `HEAD~15` — the
point to start reading git history from), plan file = "$2" (defaults to
`.tdd-features.json`).

## Resolving the since-ref

Never scan the whole repo history — that's the thing this command exists to
avoid. If `$1` is missing, don't guess it yourself: read the plan file's
existing entries first (via `list_features()`, or reading the file directly
if the MCP server isn't configured for this project) and find the newest
`recordedAt` timestamp already present. Propose the commit closest to that
timestamp (`git log --since=<that date> --oneline | tail -1`, or similar) as
a candidate since-ref, and ask me to confirm or give a different one before
proceeding. If the plan file has no `recordedAt` values yet (nothing has
ever run through the state machine), ask me directly for a since-ref.

## Gathering evidence, scoped only to the given range

Once since-ref is settled:

1. Read the plan file's entries. Only entries with `status` of `"pending"`
   or `"in_progress"` are candidates for backfilling — never touch entries
   already `"completed"` or `"abandoned"`.
2. Run `git log --oneline <since-ref>..HEAD` — scoped strictly to that
   range, not the full log. If you need more detail on a specific commit
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

- Mark an entry `"completed"` only when you found a specific commit *and*
  confirmed its test currently passes. Record that commit as
  `"backfilledFrom": "<sha>"` on the entry (a marker distinct from a normal
  `complete_feature()` run — this wasn't verified live through the state
  machine's own RED→GREEN→REFACTOR cycle, so don't hide that it was
  inferred). Fill in `testFile`/`targetFiles` if you can identify them and
  they aren't already set; leave `cyclesCompleted` as `null` if unknown
  rather than guessing a number.
- If evidence is ambiguous — a plausible commit but the description doesn't
  clearly match, or the test target doesn't exist/doesn't pass — do NOT
  mark it completed. List it separately as "unclear" for me to decide.
- Edit the plan file directly (it's a JSON array on disk) to apply
  approved updates — don't call `complete_feature()` for these, since that
  requires an active in-memory cycle this command never drives. Preserve
  every entry's existing `description`/`dependsOn` untouched.

## Report back

End with a short summary: which features were marked `"completed"` (with
their commit SHA), and which were left as-is because the evidence was
unclear, so I can resolve those manually.
