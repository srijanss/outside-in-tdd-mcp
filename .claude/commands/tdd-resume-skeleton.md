---
description: Pick up an in-progress Outside-In TDD feature that was started with /tdd-start-skeleton, without restarting it
---

Call `get_status()` first — don't guess what's in progress.

If no feature is active (`featureName` is null), say so and suggest
`/tdd-start-skeleton` instead — there is nothing to resume. The state
machine keeps no state on disk, so if the MCP server process was restarted
since the feature was started (e.g. after a `/clear` or a new session),
`get_status()` will come back empty even if you remember working on a
feature; in that case treat it the same as "no feature active" and restart
with `/tdd-start-skeleton`.

If a feature is active, resume exactly where it left off, based on the
returned phase. This mirrors `/tdd-resume`, except RED stays
skeleton-aware — it never fills in real assertions on its own:

- RED: read the current test target on disk (from `get_status()`'s
  `testFile`) and inspect it.
  - No test file / no matching test function exists yet: call
    `write_test_skeleton(testName)`, write a TODO-annotated stub (no real
    assertions), then stop and hand back — same as a fresh
    `/tdd-start-skeleton`. Don't call `run_tests()` on a stub.
  - A test function exists but still has TODO stubs / no real assertions:
    don't guess at the missing cases. Say what's still stubbed out and stop,
    waiting for the assertions to be filled in (by me, or by an explicit
    instruction from me to fill them in myself).
  - A test function exists with real assertions already written (the TODOs
    are filled in, e.g. from before an interruption): call `run_tests()`
    directly, no need to rewrite it.
- VERIFY_RED / VERIFY_GREEN: read `.claude/docs/tdd-verify-protocol.md` and
  follow it before calling `verify()` — same mandatory checkpoint
  `/tdd-start-skeleton` uses (unlike `/tdd-resume`, this doesn't skip
  straight to `verify()`).
- IMPLEMENT: check whether an implementation already exists or is partial;
  continue it or start with `write_code(filePath)`, restricted to this
  level's `targetFiles` (from `get_status()`). Use
  `drill_down(testFile, targetFiles)` if a collaborator still needs its own
  cycle, same as `/tdd-start-skeleton`.
- REFACTOR: continue or start with `refactor_code(description)`, then
  `run_tests()`.

If depth > 1 (mid drill-down), resume the top-of-stack level using the rules
above — don't touch the parent level until `return_to_parent()` is called.
A drilled-down level follows the same skeleton-aware RED rule as the base
level.

Don't re-explain the whole cycle or re-derive decisions already made — just
get back to work at the exact point `get_status()` reports.
