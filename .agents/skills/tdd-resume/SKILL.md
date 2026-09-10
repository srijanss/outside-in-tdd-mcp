---
name: tdd-resume
description: Pick up an in-progress Outside-In TDD feature after an interruption, without restarting it
---

Call `get_status()` first — don't guess what's in progress.

If no feature is active, say so and suggest `tdd-start` instead.

If a feature is active, resume exactly where the state machine left off,
based on the returned phase, using the same VERIFY_RED/VERIFY_GREEN rule as
`tdd-start` (call `verify()` directly, no human checkpoint):

- RED: check whether a test already exists at the current test target — if
  yes, call `run_tests()`; if no, `write_test(testName)` then write it.
- VERIFY_RED: show the failing test and its output, then call `verify()`.
- IMPLEMENT: check whether an implementation already exists or is partial;
  continue it or start with `write_code(filePath)`, restricted to this
  level's `targetFiles` (from `get_status()`). Use
  `drill_down(testFile, targetFiles)` if a collaborator still needs its own
  cycle, same as `tdd-start`.
- VERIFY_GREEN: show the passing implementation, then call `verify()`.
- REFACTOR: continue or start with `refactor_code(description)`, then
  `run_tests()`.

If depth > 1 (mid drill-down), resume the top-of-stack level using the rules
above — don't touch the parent level until `return_to_parent()` is called.

Don't re-explain the whole cycle or re-derive decisions already made — just
get back to work at the exact point `get_status()` reports.
