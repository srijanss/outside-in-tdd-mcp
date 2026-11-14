---
name: refresh
description: Snapshot the current TDD phase, then clear conversation context without losing your place
---

Call `get_status()` and report the exact state: feature name, phase,
drill-down depth (and the stack of test targets if depth > 1), cycle count
at the current level. This state lives in the outside-in-tdd MCP server,
not in the conversation, so clearing context does not lose it.

If no feature is active, say so and stop — there's nothing to preserve, so
a plain context clear is enough on its own.

If a feature is active, say plainly: clear context now, then invoke
`tdd-resume` to pick up exactly at the point just reported. Do not clear
context directly — that's a client-specific action, not something
invocable from inside a tool call.
