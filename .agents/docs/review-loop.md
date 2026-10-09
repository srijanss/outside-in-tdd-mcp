# Review loop

Shared by `implement-and-review` and `review-and-fix`. Input: a start SHA
(`<start>`; the review covers `<start>..HEAD`), plus optional reviewer
options (`reviewer`, `model`, `thinking`) to pass to `start_review` as given
— omit any that weren't given so the config defaults apply.

Everything the reviewer sees is committed work: the working tree must be
clean and no TDD feature may be in progress (`start_review` refuses
otherwise).

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
