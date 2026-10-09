---
name: review-and-fix
description: Review already-committed work with an external model via the outside-in-tdd server, then fix the findings through the TDD cycle and re-review
---

You have been given a commit range `<sha>..HEAD` (or `<sha>...HEAD`) and
optional options: `--reviewer pi|claude`, `--model <model>`,
`--thinking <level>`, `--verify`.

If the range is missing or isn't of that form, ask for it and wait.
Normalize `...` to `..`. Check the working tree is clean and that no TDD
feature is in progress (`get_status()`); if either isn't true, say so and
stop rather than committing someone else's work.

Then read `.agents/docs/review-loop.md` and follow it with `<start>` = the
sha given. Fixes use the `tdd-start` flow, or `tdd-start-verify` if
`--verify` was given.

If the range holds several independent features, run the loop once per
feature range instead (each with its own start SHA) when the user lists
them separately; otherwise treat the whole range as one review.

Finish with a short report: rounds run, findings fixed / rejected /
deferred, open low-severity findings, and whether a human decision is
needed.
