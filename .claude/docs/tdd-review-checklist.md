# End-of-feature review checklist

Ask via `AskUserQuestion` (multi-select; plain text if unavailable) which
to check, within the given scope:
- Missing tests / edge cases / error cases
- Security issues or leaks
- Bugs
- Performance issues
- Nothing right now

For each picked category, review only the files in scope and produce
concrete findings:
- **Missing tests/edge cases** — specific untested scenarios (invalid
  input, boundary values, drill-down/nested or repeated calls), concrete
  enough to write a test from directly.
- **Security issues or leaks** — use the `security-review` skill if
  available; otherwise check manually (injection, secret/credential
  leakage, unsafe subprocess or file-path handling).
- **Bugs** — use the `code-review` skill if available; otherwise review
  manually for correctness.
- **Performance issues** — concrete inefficiencies (redundant I/O or
  subprocess calls, avoidable O(n²) work).

If "Nothing right now" was picked, stop here.

Present findings as a numbered list, one line each, `file:line` where it
applies. Don't fix anything yet. Then ask which finding, if any, should
become the next TDD feature or bugfix — that's the feature name (and test
target) for a new cycle.
