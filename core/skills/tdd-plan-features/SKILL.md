---
name: tdd-plan-features
description: Read a plan/design doc and generate (or extend) .tdd-features.json — smallest features, with dependencies
---

You have been given a plan doc path (a markdown design/plan document to
read) and optionally a features file path (defaults to
`.tdd-features.json`).

If the plan doc path is missing, ask for it — don't guess which file in the
repo is "the plan".

## Breaking the doc into features

Read the plan doc fully. Break it down into the smallest features that each
make sense as one Outside-In TDD base-level cycle here — i.e. each one is a
single demonstrable behavior slice with its own acceptance/functional test,
matching the granularity `init_feature(featureName, testFile, targetFiles)`
expects (see SPEC.md's "Feature Lifecycle" and README.md). Not a task list
("write docs", "set up CI") — only things a failing test could capture.

For each feature, work out:

- `featureName`: a short, unique, kebab-case identifier (this is the key
  `dependsOn` references and what later gets passed to `init_feature`).
- `description`: one or two sentences, enough for a future session (or
  `tdd-backfill-features`) to recognize it without re-reading the plan doc.
- `dependsOn`: only real dependencies — this feature's implementation or
  test genuinely can't be built/verified until another one is done (e.g. it
  needs a model/schema/endpoint the other feature introduces). Don't add a
  dependency just because the plan doc lists them in that order; most
  features in a plan are independent. Keep the dependency graph acyclic —
  if a cycle turns up, stop and flag it instead of guessing which edge to
  drop.

## Merging with an existing features file

Read the features file (the given path, or the default) with
`list_features()` if the MCP server is configured for this project,
otherwise by reading the file directly. If it doesn't exist yet, this is
creating it fresh — every entry starts `"status": "draft"`.

If it already exists:

- Never modify or remove an existing entry — not its `status`, not its
  `dependsOn`, not its `description`. Entries already `"in_progress"` or
  `"completed"` represent real work; this skill only adds to the plan.
- For each feature derived from the doc, check whether it already matches
  an existing entry (same `featureName`, or clearly the same feature under
  a different name/description). Skip it if so — don't create a duplicate.
  If the match is ambiguous, list it separately and ask rather than
  silently deciding.
- Append only the genuinely new entries, each `"status": "draft"`,
  `dependsOn` referencing existing `featureName`s (old or newly-added)
  where applicable.

## Before writing

Show the full list of features about to be added (name, description,
dependsOn) before writing the file — this shapes all future dependency
gating via `init_feature`, so it's worth a quick look before it's
committed to disk. Once confirmed (or there's no reason to think there'd
be an objection — use judgment on how much this plan matters), write the
merged array to the features file as `"status": "draft"` entries, then call
`approve_plan()` (or say to) before any of them can be started with
`init_feature`.
