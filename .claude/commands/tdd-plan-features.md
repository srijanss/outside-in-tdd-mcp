---
description: Read a plan/design doc and generate (or extend) .tdd-features.json — smallest features, with dependencies
argument-hint: <plan-doc-path> [features-file]
---

Arguments: plan doc = "$1" (a markdown design/plan document to read),
features file = "$2" (defaults to `.tdd-features.json`).

If `$1` is missing, ask me for the doc path — don't guess which file in the
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
  `dependsOn` references and what you'll later pass to `init_feature`).
- `description`: one or two sentences, enough for a future session (or
  `/tdd-backfill-features`) to recognize it without re-reading the plan doc.
- `dependsOn`: only real dependencies — this feature's implementation or
  test genuinely can't be built/verified until another one is done (e.g. it
  needs a model/schema/endpoint the other feature introduces). Don't add a
  dependency just because the plan doc lists them in that order; most
  features in a plan are independent. Keep the dependency graph acyclic —
  if you find a cycle, stop and flag it to me instead of guessing which
  edge to drop.

## Merging with an existing features file

Read the features file (if `$2` wasn't given, the default path) with
`list_features()` if the MCP server is configured for this project,
otherwise by reading the file directly. If it doesn't exist yet, you're
creating it fresh — every entry starts `"status": "draft"`.

If it already exists:

- Never modify or remove an existing entry — not its `status`, not its
  `dependsOn`, not its `description`. Entries already `"in_progress"` or
  `"completed"` represent real work; this command only adds to the plan.
- For each feature you derived from the doc, check whether it already
  matches an existing entry (same `featureName`, or clearly the same
  feature under a different name/description). Skip it if so — don't
  create a duplicate. If the match is ambiguous, list it separately and
  ask me rather than silently deciding.
- Append only the genuinely new entries, each `"status": "draft"`,
  `dependsOn` referencing existing `featureName`s (old or newly-added)
  where applicable.

## Before writing

Show me the full list of features you're about to add (name, description,
dependsOn) before writing the file — this shapes all future dependency
gating via `init_feature`, so it's worth a quick look before it's
committed to disk. Once I confirm (or you have no reason to think I'd
object — use judgment on how much this plan matters), write the merged
array to the features file as `"status": "draft"` entries, then call
`approve_plan()` (or tell me to) before any of them can be started with
`init_feature`.
