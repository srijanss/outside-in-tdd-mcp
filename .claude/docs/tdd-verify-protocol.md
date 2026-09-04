# Verify protocol (VERIFY_RED / VERIFY_GREEN)

At VERIFY_RED or VERIFY_GREEN, before calling `verify()`:

1. Show what needs judging: the failing test + output (RED), or the
   implementation + passing output (GREEN).
2. Ask via `AskUserQuestion` — options like "Looks right, continue" /
   "Not right, let me fix it" / "Cancel this feature". If that tool is
   unavailable or the prompt doesn't resolve, fall back to plain text
   asking for a "go ahead" reply. Always wait for an answer either way.
3. Act on it:
   - **Confirmed** → call `verify()`, continue.
   - **Needs a fix** → don't call `verify()`; go fix the test (RED) or the
     implementation (IMPLEMENT) per the feedback instead.
   - **Cancelled** → call `reset_feature()` immediately, tell the user
     plainly the feature was reset, and stop — no further tool calls.

Never call `verify()` on your own initiative. It's the user's call to make
through you, not yours to make on their behalf.
