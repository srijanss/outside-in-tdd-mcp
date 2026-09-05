# End-of-feature review checklist

Ask via `AskUserQuestion` (multi-select; plain text if unavailable) which
to check, within the given scope. `AskUserQuestion` allows at most 4
options per question, so offer exactly these 4 — don't add a 5th "nothing"
option, it will make the tool call fail validation:
- Missing tests / edge cases / error cases
- Security issues or leaks
- Bugs
- Performance issues

To decline entirely, the user can pick "Other" (always available) and
answer "nothing" / "skip" — treat that the same as picking none.

For each picked category, review only the files in scope and produce
concrete findings:
- **Missing tests/edge cases** and **Bugs** — spawn the `review-finder`
  agent (Haiku — cheap, unverified first pass) scoped to exactly the files
  in scope, once per category or combined in one call. Its output is
  candidates only; verify each one yourself (read the actual code/line)
  before reporting it as a finding — drop anything that doesn't hold up.
  Fall back to the `code-review` skill or a manual read if the agent is
  unavailable.
- **Security issues or leaks** — use the `security-review` skill if
  available; otherwise check manually (injection, secret/credential
  leakage, unsafe subprocess or file-path handling).
- **Performance issues** — concrete inefficiencies (redundant I/O or
  subprocess calls, avoidable O(n²) work).

If nothing was picked (declined via "Other"), stop here.

Present findings as a numbered list, one line each, `file:line` where it
applies. Don't fix anything yet. Then ask which finding, if any, should
become the next TDD feature or bugfix — that's the feature name (and test
target) for a new cycle.
