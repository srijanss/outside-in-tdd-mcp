---
description: Start a new Outside-In TDD feature via the outside-in-tdd MCP server, advancing through VERIFY_RED/VERIFY_GREEN without a human checkpoint
argument-hint: <feature-name> <test-file>
---

Arguments given: feature name = "$1", test target = "$2".

Before calling `init_feature`, resolve both arguments — don't guess silently:

- If the feature name is missing, ask me for it and wait for my answer.
- If the test target is missing entirely, ask me for it and wait for my
  answer.
- If the test target looks like a directory/app rather than a specific test
  file (e.g. "app/", or a path with no file extension that exists as a
  directory), don't treat it as the test target as-is. Instead:
  1. Look at how existing apps/modules in this project lay out their tests
     (a single `tests.py`, a `tests/` package with `test_*.py` files,
     something else) to find the actual convention in use.
  2. Propose a specific test file path that follows that convention (e.g.
     `app/tests/test_<feature_name>.py`), and ask me to confirm or correct
     it before creating anything.
  Only proceed once we've settled on one concrete file path.

Once both are settled, using the outside-in-tdd MCP server's tools (not your
own file-editing tools in place of them), start the feature with
`init_feature(featureName, testFile, targetFiles)` using the confirmed name
and file. `targetFiles` is the implementation file(s) you expect the
base-level cycle to write directly — `write_code` will be blocked for
anything outside that set (see IMPLEMENT below).

## VERIFY_RED / VERIFY_GREEN

Whenever the phase is VERIFY_RED or VERIFY_GREEN, call `verify()` directly
to advance — no human checkpoint is required in this command. Still show
what's being verified (the failing test + output at VERIFY_RED, or the
implementation + passing output at VERIFY_GREEN) as part of your normal
narration before moving on. Use `/tdd-start-verify` instead if you want me
to explicitly confirm each checkpoint before `verify()` is called.

## The cycle

Work through the phases using the server's tools at each step, actually
writing the corresponding file changes yourself alongside each call (the
tools are phase checkpoints, not file writers):

1. RED: `write_test(testName)`, write the failing test to disk, then
   `run_tests()`. This should move the phase to VERIFY_RED.
2. VERIFY_RED: call `verify()` per "VERIFY_RED / VERIFY_GREEN" above.
3. IMPLEMENT: `write_code(filePath)` only for a `filePath` in this level's
   declared `targetFiles`, write the implementation, then `run_tests()`
   until it passes. The moment IMPLEMENT needs to touch any other file —
   new or existing, a different app, a unit test, a new module, anything
   not already in `targetFiles` — that content needs its own test first:
   never write it directly. Use `drill_down(testFile, targetFiles)`
   instead, declaring the file(s) that nested cycle owns — it runs its own
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
calling `complete_feature()`, read `.claude/docs/tdd-regression-check.md`
and follow it. Call `get_status()` any time you're unsure what's currently
allowed — every tool response already includes it. Never skip straight to
writing passing code without a real RED failure first.

## After the feature completes

Once `complete_feature()` succeeds, briefly summarize what was built, then
read `.claude/docs/tdd-review-checklist.md` and follow it, scoped to the
files/tests touched this cycle (not the whole repo). A chosen finding
becomes the next `/tdd-start` feature (test target resolved as above).
