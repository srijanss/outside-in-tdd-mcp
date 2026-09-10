---
name: tdd-start-skeleton
description: Start a new Outside-In TDD feature (skeleton-first) via the outside-in-tdd MCP server
---

You have been given a feature name and a test target (the caller resolves
these before invoking this skill — see below if either is missing).

Before calling `init_feature`, resolve both — don't guess silently:

- If the feature name is missing, ask for it and wait for the answer.
- If the test target is missing entirely, ask for it and wait for the
  answer.
- If the test target looks like a directory/app rather than a specific test
  file (e.g. "app/", or a path with no file extension that exists as a
  directory), don't treat it as the test target as-is. Instead:
  1. Look at how existing apps/modules in this project lay out their tests
     (a single `tests.py`, a `tests/` package with `test_*.py` files,
     something else) to find the actual convention in use.
  2. Propose a specific test file path that follows that convention (e.g.
     `app/tests/test_<feature_name>.py`), and ask for confirmation or a
     correction before creating anything.
  Only proceed once one concrete file path is settled.
- `targetFiles` is not something to ask for. Infer it the same way the test
  target is resolved: from the feature name, the test file's location, and
  this project's existing module layout, work out which implementation
  file(s) the base-level cycle should own (an existing file expected to be
  edited, or a new path that mirrors the test file's package/naming
  convention). State what was inferred as part of normal narration before
  calling `init_feature` so it can be corrected, but don't stop and wait for
  confirmation the way missing feature name/test target require.

Once the feature name and test file are settled and `targetFiles` inferred,
using the outside-in-tdd MCP server's tools (not other file-editing tools in
place of them), start the feature with
`init_feature(featureName, testFile, targetFiles)`. `targetFiles` is the
implementation file(s) the base-level cycle will write directly —
`write_code` will be blocked for anything outside that set (see IMPLEMENT
below).

For the RED phase, use `write_test_skeleton(testName)` instead of
`write_test` — stub the test function(s) with TODO comments describing the
cases to cover, but don't fill in real assertions yet. Write that skeleton
to disk, then stop and hand back: someone else fills in the TODOs with the
actual test-case detail. Once told to continue, use `write_test` (or
`write_test_skeleton` again) to fill in the real assertions matching what
was written, then `run_tests()`.

## How to verify (VERIFY_RED / VERIFY_GREEN)

Whenever the phase is VERIFY_RED or VERIFY_GREEN, read
`.agents/docs/tdd-verify-protocol.md` and follow it before calling
`verify()`. (At VERIFY_RED, "fix the test" means re-filling the
assertions, same as elsewhere in this workflow.)

## The rest of the cycle

From there, work through the rest of the cycle the same way as usual. Once
`run_tests()` after the real assertions fails, the phase moves to
VERIFY_RED:

1. VERIFY_RED: follow "How to verify" above before calling `verify()`.
2. IMPLEMENT: `write_code(filePath)` only for a `filePath` in this level's
   declared `targetFiles`, write the implementation, then `run_tests()`
   until it passes. The moment IMPLEMENT needs to touch any other file —
   new or existing, a different app, a unit test, a new module, anything
   not already in `targetFiles` — that content needs its own test first:
   never write it directly. Use `drill_down(testFile, targetFiles)`
   instead, inferring `targetFiles` the same way as above (from the new
   test file and what it needs), declaring the file(s) that nested cycle
   owns — it runs its own
   independent RED->VERIFY_RED->IMPLEMENT->VERIFY_GREEN->REFACTOR cycle,
   including its own verify checkpoints. Call `return_to_parent()` once
   that's done, or `abandon_drill_down()` if it turns out unnecessary, then
   resume writing only this level's own `targetFiles` (e.g. wiring in what
   the drill-down just built).
3. VERIFY_GREEN: follow "How to verify" above before calling `verify()`.
4. REFACTOR: `refactor_code(description)`, then `run_tests()` to close the
   cycle (back to RED, cycle count +1).

Repeat until the base-level feature test genuinely passes. Then, before
calling `complete_feature()`, read `.agents/docs/tdd-regression-check.md`
and follow it. Call `get_status()` any time it's unclear what's currently
allowed.

## After the feature completes

Once `complete_feature()` succeeds, briefly summarize what was built, then
read `.agents/docs/tdd-review-checklist.md` and follow it, scoped to the
files/tests touched this cycle (not the whole repo). A chosen finding
becomes the next `tdd-start-skeleton` feature (test target resolved as
above).
