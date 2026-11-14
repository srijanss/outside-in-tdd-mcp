---
name: tdd-complete
description: Verify a feature is genuinely done and mark it complete via complete_feature()
---

Call `get_status()`. `complete_feature()` requires depth 1 and RED phase
with `cycleCount >= 1` — if that's not the current state, report exactly
what's blocking it (e.g. "still at depth 2, drill-down in progress" or
"phase is IMPLEMENT, current cycle isn't closed") and stop. Don't
force-advance phases just to get there.

If eligible: read `.agents/docs/tdd-regression-check.md` and follow it
first. Then call `complete_feature()`.

Once it succeeds, summarize: files touched, tests added, cycle count. Do
not commit — per project instructions, always ask before creating a commit,
even right after a feature completes.
