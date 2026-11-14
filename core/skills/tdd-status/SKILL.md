---
name: tdd-status
description: Report current TDD feature status only — phase, depth, cycle count
---

Call `get_status()`. Report only: feature name, current phase, drill-down
depth (and the stack of test targets if depth > 1), cycle count at the
current level. No explanation of what the phase means, no next-step
suggestions unless asked.

If no feature is active, say so and stop.
