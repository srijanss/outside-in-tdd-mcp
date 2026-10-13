---
name: implement-and-review
description: Implement one or more features with the TDD cycle, commit them, have an external model review the commits, then fix the findings and re-review
---

You have been given one or more feature descriptions and optional options:
`--reviewer pi|claude`, `--model <model>`, `--thinking <level>`, `--verify`.

For each feature, in order:

1. Check no tracked file has uncommitted changes (untracked files don't
   count; `git status --porcelain --untracked-files=no`) and no TDD feature
   is in progress. Record
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

## Review categories

Every unattended review must cover all four checklist categories, not only the review-only procedure's default two (bugs and missing tests):

1. **Bugs**: logic errors, wrong conditions, unhandled states.
2. **Missing tests**: edge cases and error/exception paths.
3. **Security issues or leaks**: injection, secret/credential leakage, unsafe subprocess or file-path handling.
4. **Performance issues**: redundant I/O or subprocess calls, avoidable O(n^2) work.

Put this as an explicit caller instruction in `handoff.md` and in the reviewer launch prompt, so it overrides the review-only procedure's default categories. Require each recorded finding's `category` to be one of these four values.
