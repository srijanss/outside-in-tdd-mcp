# End-of-feature review checklist

Takes a `scope` key (from the calling skill). Call `list_review_findings`
for that scope first — it's shared across agents/tools (Claude, Codex), so
another session may have already recorded candidates or confirmed findings
for this exact scope. Show anything returned before running a fresh check;
don't re-verify a finding already marked `confirmed` unless the code at
its `file`/`line` has visibly changed since.

Ask, via a structured multi-select choice tool if one is available
(otherwise plain text), which to check, within the given scope. If using
such a tool and it caps options per question (e.g. at 4), offer exactly
these 4 — don't add a 5th "nothing" option, it may make the call fail
validation:
- Missing tests / edge cases / error or exception cases
- Security issues or leaks
- Bugs
- Performance issues

To decline entirely, an "Other" / free-text option (or a plain-text
"nothing" / "skip" reply) counts as picking none.

For each picked category, review only the files in scope and produce
concrete findings:
- **Missing tests/edge cases/error cases** and **Bugs** — spawn the
  `review-finder` subagent (a fast, cheap model — an unverified first
  pass) scoped to exactly the files in scope, once per category or
  combined in one call. It flags missing tests/edge cases, missing error
  or exception cases (an error return, raised exception, or failure
  branch that exists in the code but has no test asserting on it), and
  bugs. Its output is candidates only and must be verified before being
  reported as a finding — drop anything that doesn't hold up. Fall back to
  the `code-review` skill or a manual read if the subagent is unavailable.

  If there are candidates to verify, ask (structured choice if available,
  otherwise plain text) whether to verify them yourself (default) or hand
  verification to the `review-verifier` subagent on a model of the user's
  choosing:
  - **Verify it yourself** (default) — read the actual code/line for each
    candidate and confirm or drop it, same as before.
  - **Verify with another model** — ask which model to use (don't assume
    one — `review-verifier` intentionally has no model pinned in its
    frontmatter), then spawn `review-verifier` with that model as an
    explicit override, giving it the candidate list plus the files in
    scope. Use its CONFIRMED/REJECTED output to decide what to report — a
    stronger/pricier model costs more per run, but it's a one-time cost
    per feature, not per commit, so it's optional and worth it when the
    user wants a second opinion on the candidates rather than trusting the
    caller's own read.
- **Security issues or leaks** — use the `security-review` skill if
  available; otherwise check manually (injection, secret/credential
  leakage, unsafe subprocess or file-path handling).
- **Performance issues** — concrete inefficiencies (redundant I/O or
  subprocess calls, avoidable O(n²) work).

If nothing was picked (declined via "Other"), stop here.

Present findings as a numbered list, one line each, `file:line` where it
applies. Don't fix anything yet.

Persist every finding via `record_review_finding(scope, finding)` — one
call per finding, each `finding` an object with at least `id` (a short
stable slug, e.g. `missing-lock`), `status` (`candidate` if unverified,
`confirmed` if verified this run, `rejected` if a carried-forward
candidate didn't hold up), `severity`, `file`, `line`, and `summary`. This
is what lets a review started by one tool/model be picked up and
continued by another — do this even if the user declines to act on any
finding right now.

Then ask which finding, if any, should become the next TDD feature or
bugfix — that's the feature name (and test target) for a new cycle. If one
is picked, update its persisted `status` to `fixed` once that cycle
completes (via `record_review_finding` again with the same `id`).
