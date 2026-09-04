---
description: Start a new Outside-In TDD feature (skeleton-first) via the outside-in-tdd MCP server
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
`init_feature(featureName, testFile)` using the confirmed name and file.

For the RED phase, use `write_test_skeleton(testName, code)` instead of
`write_test` — stub the test function(s) with TODO comments describing the
cases to cover, but don't fill in real assertions yet. Write that skeleton
to disk, then stop and hand back to me: I'll fill in the TODOs with the
actual test-case detail. Once I tell you to continue, use `write_test` (or
`write_test_skeleton` again) to fill in the real assertions matching what I
wrote, then `run_tests()`.

## How to verify (VERIFY_RED / VERIFY_GREEN)

Whenever the phase is VERIFY_RED or VERIFY_GREEN, read
`.claude/docs/tdd-verify-protocol.md` and follow it before calling
`verify()`. (At VERIFY_RED, "fix the test" means re-filling the
assertions, same as elsewhere in this command.)

## The rest of the cycle

From there, work through the rest of the cycle the same way as usual. Once
`run_tests()` after the real assertions fails, the phase moves to
VERIFY_RED:

1. VERIFY_RED: follow "How to verify" above before calling `verify()`.
2. IMPLEMENT: `write_code(filePath, code)`, write the implementation, then
   `run_tests()` until it passes. If a piece needs its own test first (a
   different app, a unit test, anything), use `drill_down(testFile)` instead
   of switching test files informally — it runs its own independent
   RED->VERIFY_RED->IMPLEMENT->VERIFY_GREEN->REFACTOR cycle, including its
   own verify checkpoints. Call `return_to_parent()` once that's done, or
   `abandon_drill_down()` if it turns out unnecessary.
3. VERIFY_GREEN: follow "How to verify" above before calling `verify()`.
4. REFACTOR: `refactor_code(description)`, then `run_tests()` to close the
   cycle (back to RED, cycle count +1).

Repeat until the base-level feature test genuinely passes. Then, before
calling `complete_feature()`, read `.claude/docs/tdd-regression-check.md`
and follow it. Call `get_status()` any time you're unsure what's currently
allowed.

## After the feature completes

Once `complete_feature()` succeeds, briefly summarize what was built, then
read `.claude/docs/tdd-review-checklist.md` and follow it, scoped to the
files/tests touched this cycle (not the whole repo). A chosen finding
becomes the next `/tdd-start-skeleton` feature (test target resolved as
above).
