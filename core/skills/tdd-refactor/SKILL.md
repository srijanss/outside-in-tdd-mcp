---
name: tdd-refactor
description: Run only the REFACTOR phase — structural cleanup, no new behavior
---

You have been given an optional description of the refactor (the caller
resolves this before invoking this skill).

Call `get_status()`. If the phase isn't REFACTOR, say so and stop — don't
force a phase change to get there.

If the phase is REFACTOR: call `refactor_code(description)` using the given
description if there is one, otherwise ask for one. Make structural-only
changes — renames, extraction, dedup, dead code removal — no new behavior
and no new test coverage. Then call `run_tests()`.

If tests fail, fix the refactor (not the tests) and re-run until green.
Report only what changed and the final test result.
