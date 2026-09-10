---
name: tdd-start
description: Start a new Outside-In TDD feature via the outside-in-tdd MCP server, advancing through VERIFY_RED/VERIFY_GREEN without a human checkpoint
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

## VERIFY_RED / VERIFY_GREEN

Whenever the phase is VERIFY_RED or VERIFY_GREEN, call `verify()` directly
to advance — no human checkpoint is required in this workflow. Still show
what's being verified (the failing test + output at VERIFY_RED, or the
implementation + passing output at VERIFY_GREEN) as part of normal
narration before moving on. Use the `tdd-start-verify` variant instead if
each checkpoint should be explicitly confirmed before `verify()` is called.

## The cycle

Work through the phases using the server's tools at each step, actually
writing the corresponding file changes alongside each call (the tools are
phase checkpoints, not file writers):

1. RED: `write_test(testName)`, write the failing test to disk, then
   `run_tests()`. This should move the phase to VERIFY_RED.
2. VERIFY_RED: call `verify()` per "VERIFY_RED / VERIFY_GREEN" above.
3. IMPLEMENT: `write_code(filePath)` only for a `filePath` in this level's
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
4. VERIFY_GREEN: call `verify()` per "VERIFY_RED / VERIFY_GREEN" above.
5. REFACTOR: `refactor_code(description)`, then `run_tests()` to close the
   cycle (back to RED, cycle count +1).

Repeat RED->VERIFY_RED->IMPLEMENT->VERIFY_GREEN->REFACTOR (and drill down as
needed) until the base-level feature test genuinely passes. Then, before
calling `complete_feature()`, read `.agents/docs/tdd-regression-check.md`
and follow it. Call `get_status()` any time it's unclear what's currently
allowed — every tool response already includes it. Never skip straight to
writing passing code without a real RED failure first.

## After the feature completes

Once `complete_feature()` succeeds, briefly summarize what was built, then
read `.agents/docs/tdd-review-checklist.md` and follow it, scoped to the
files/tests touched this cycle (not the whole repo). A chosen finding
becomes the next `tdd-start` feature (test target resolved as above).
