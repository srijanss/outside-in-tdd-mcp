---
name: implement-and-review
description: Implement one or more features with the TDD cycle, commit them, have an external model review the commits, then fix the findings and re-review
---

You have been given one or more feature descriptions and optional options:
`--reviewer pi|claude`, `--model <model>`, `--thinking <level>`, `--verify`.

For each feature, in order:

1. Check the working tree is clean and no TDD feature is in progress. Record
   the start SHA: `git rev-parse HEAD`.
2. Implement it with the `tdd-start` flow (`tdd-start-verify` if `--verify`
   was given), resolving the feature name, test target and `targetFiles` as
   that skill describes.
3. When `complete_feature` succeeds, commit the work (one or more commits).
4. Read `.agents/docs/review-loop.md` and follow it with `<start>` = the SHA
   from step 1. Pass the reviewer options through.

Review per feature, not once at the end, so each review stays small and its
findings stay attributable. If a loop ends in `escalate`, stop and hand
over to the human before starting the next feature.

Finish with a short report per feature: commits, rounds run, findings fixed
/ rejected / deferred, open low-severity findings, and anything needing a
human decision.
