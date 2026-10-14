# Review loop

Shared by `implement-and-review` and `review-and-fix`. Input: a start SHA
(`<start>`; the review covers `<start>..HEAD`), plus optional reviewer
options (`reviewer`, `model`, `thinking`) to pass to `start_review` as given
— omit any that weren't given so the config defaults apply.

Everything the reviewer sees is committed work: no tracked file may have
uncommitted changes (`git status --porcelain --untracked-files=no` is empty;
untracked files don't count) and no TDD feature may be in progress
(`start_review` refuses the latter).

## Each round

1. `start_review(range="<start>..HEAD", ...)`. Repeating the same range is
   how the next round is requested — the server reviews only the new
   commits and gives the reviewer the findings ledger. Don't change the
   start SHA between rounds.
2. `await_review(reviewId, timeoutSeconds=300)`; call it again while the
   status is `pending`.
   - `failed`: show the error and stop. A failed review is not a clean one.
3. Show the findings briefly (id, severity, file:line, claim), then act on
   `decision`:
   - `done`: stop. Summarize any open low-severity findings in a few lines
     (don't fix them) and list anything rejected/deferred with its reason.
   - `escalate`: stop and hand the `reason` and the open blocking findings
     to the human. Don't try another round.
   - `continue`: handle every open medium-or-higher finding, then go to the
     next round.

## Handling a finding

Read the code at `file`/`line` first. Don't take the claim on trust.

- **Valid and behavioral** — fix it as its own TDD feature using the
  `tdd-start` flow (or `tdd-start-verify` if `--verify` was given):
  `init_feature(featureName, testFile, targetFiles, reviewFindingId=<id>,
reviewFindingScope=<scope>)`, where `<scope>` is the `scope` from the
  `await_review` result. The failing test comes first. `complete_feature`
  marks the finding fixed — never set `fixed` by hand.
- **Valid but not behavioral** (naming, structure, duplication) — a
  refactor-only feature: still `init_feature` with the finding id/scope, a
  test that pins the existing behavior, then only the REFACTOR phase.
- **Wrong or not worth doing** — `record_review_finding(scope, {...finding,
"status": "rejected", "reason": "<why>"})`. Use `deferred` for real but
  out of scope. A reason is required; be specific.

Commit after each fixed finding (one commit per finding, message naming the
finding id). Then run the next round on the same range.

If every blocking finding was rejected or deferred there is nothing new to
commit and `start_review` will say so: stop, and report the rejections to
the human.

## Limits

At most 3 rounds (the server escalates at the cap). Never call
`approve_plan`. Never edit the findings or rounds files directly.

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

`start_review` already puts all four checklist categories in the reviewer prompt and requires each finding's `category` to be one of `bugs`, `missing-tests`, `security`, `performance`; a finding without one fails the review. No caller instruction is needed in `handoff.md` or the launch prompt for `start_review`. Add one only when launching a reviewer outside `start_review`.
