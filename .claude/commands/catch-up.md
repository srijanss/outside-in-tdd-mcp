---
description: Reorient a fresh session (after a restart, /clear, or reconnecting the MCP server) using live MCP state instead of a manual summary
---

Call `session_start()` — this reads directly from disk/MCP state and
bundles the feature ledger, current phase/drill-down status, a tail of
`.tdd-session.log`, and a tail of the durable research log
(`.tdd-research.json`).

Report back plainly, in this order:

1. Feature status — active feature, phase, drill-down depth, from the
   ledger and `get_status()` if a feature is active.
2. The most recent research/discussion log entries — especially anything
   recorded via `/checkpoint`, since that's likely what was being
   discussed right before the session ended.
3. The concrete next step, if one is evident from the above.

If a feature is actively mid-cycle, tell me `/tdd-resume` will pick it up
exactly where it left off — don't restate the full cycle rules yourself.

If everything comes back empty (no features, no log entries), say so
plainly and ask what to work on — don't invent context that isn't there.
