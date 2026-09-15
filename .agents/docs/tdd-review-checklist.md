# End-of-feature review checklist

STOP. Before doing anything else — before reading diffs, before spawning
`review-finder`, before any other step in this checklist — call
`list_review_findings(scope)` for the `scope` key given by the calling
skill. This is not optional and not a "nice to check first": the findings
store is shared across agents/tools (Claude, Codex), so another session may
have already recorded candidates or confirmed findings for this exact
scope, and re-deriving them from scratch wastes a full diff re-scan.

Show anything returned before running a fresh check. Don't re-verify a
finding already marked `confirmed` unless the code at its `file`/`line` has
visibly changed since.

If `list_review_findings` returned any findings, skip the category
question below by default and go straight to reusing them: present the
list and move on to "which finding, if any, should become the next TDD
feature" near the end of this checklist. Only fall through to asking the
category question (and running a fresh check) if the user explicitly asks
for one — e.g. "also check security", "re-scan", "run it again" — or if
none were returned.

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
bugfix — that's the feature name (and test target) for a new cycle. When
handing off to `tdd-start`/`tdd-start-verify`/`tdd-start-skeleton`, also
pass along that finding's `id` and this review's `scope` — the skill
passes them through as `reviewFindingId`/`reviewFindingScope` on
`init_feature`, and `complete_feature` then automatically records it as
`fixed` (which removes it from the store) once the cycle finishes. No
manual `record_review_finding` call needed in that case — only fall back
to calling it by hand if the fix wasn't done through a linked
`tdd-start`-family cycle.
