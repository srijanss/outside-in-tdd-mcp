# Regression check (before complete_feature)

The server now runs this automatically: when `run_tests()` is called in
REFACTOR phase at the base level (depth 1) and the cycle's own target
passes, it also runs the whole suite (`defaultTestDir` from
`.tdd-config.json`) through the same adapter before letting the phase
advance back to RED. If that full-suite run has failures, they're merged
into the result (prefixed `REGRESSION:`) and REFACTOR stays open instead
of closing — so `complete_feature()` can't become reachable on top of a
regression, without you needing to remember a separate step.

Before running that sweep, `run_tests()` returns
`needsRegressionScopeConfirmation` with three scopes:

- `suggestedScope` — the default to sweep. Unless the project set
  `regressionScopeDefault` in `.tdd-config.json`, it is what the
  uncommitted changes can affect, when the adapter ships a `scope.sh` that
  maps changed files to tests; otherwise the whole `defaultTestDir`. The
  project may have made it the changed scope (`"changed"`) or the full
  suite (`"full"`).
- `changedScope` — only the tests closest to the change. `"skip"` when
  nothing beyond this cycle's own target needs to run (that target already
  ran in the same call).
- `fullSuiteScope` — the whole `defaultTestDir`.

Re-call `run_tests(regressionScope=<suggestedScope>)` by default. Use
`fullSuiteScope` only when the change is broad (shared fixtures, config,
the adapter itself) or the user asks for it — the full suite still runs in
review/CI. `"skip"` skips the sweep.

When `regressionScopeDefault` is `"changed"`, the full suite runs at the
orchestrator's gate, not here: never re-run `fullSuiteScope` as a
double-check after a narrow sweep, and don't hand-run a full-suite sweep
after review fixes. A `regressionScopeNote` in the response (the changes
map to no narrower scope) means the same: take `suggestedScope` as given.

This only fires at depth 1 (nested drill-down cycles skip it — running the
whole suite after every nested cycle would be wasteful) and only when
`defaultTestDir` is set in the config.

If a `REGRESSION:`-prefixed failure shows up in `run_tests()`'s result
while closing out a cycle: that's something else you touched breaking,
not this feature's own test. Fix it (or ask the user how they want to
handle it) before trying `run_tests()` again — don't treat it as this
cycle's normal RED→IMPLEMENT loop.
