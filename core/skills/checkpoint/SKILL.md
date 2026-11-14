---
name: checkpoint
description: Save a summary of the current discussion to the durable research log, so a fresh session can catch up without a manual summary
---

Look back over this conversation and identify:

- What's being discussed (the topic, not a transcript)
- Any decisions made and the reasoning behind them
- Open questions or unresolved threads
- The concrete next step, if one is evident

Write this as a tight summary — a short paragraph or a few bullets, not a
full transcript.

If this discussion is about a specific feature in `.tdd-features.json`,
note its `featureName`. Otherwise omit it.

Call `record_research(source="checkpoint <today's date>", summary=<the
summary>, relatedFeature=<featureName if applicable>)`.

Confirm: the summary recorded, and that a fresh session can pick this up
with `catch-up`.

This is for everything `refresh` doesn't cover — open discussion, planning,
decisions not yet turned into a feature. Live TDD phase state (what
`refresh` preserves) already survives a restart on its own via
`get_status()`; this skill isn't needed for that.
