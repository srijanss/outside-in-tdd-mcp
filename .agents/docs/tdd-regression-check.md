# Regression check (before complete_feature)

The server now runs this automatically: when `run_tests()` is called in
REFACTOR phase at the base level (depth 1) and the cycle's own target
passes, it also runs the whole suite (`defaultTestDir` from
`.tdd-config.json`) through the same adapter before letting the phase
advance back to RED. If that full-suite run has failures, they're merged
into the result (prefixed `REGRESSION:`) and REFACTOR stays open instead
of closing — so `complete_feature()` can't become reachable on top of a
regression, without you needing to remember a separate step.

This only fires at depth 1 (nested drill-down cycles skip it — running the
whole suite after every nested cycle would be wasteful) and only when
`defaultTestDir` is set in the config.

If a `REGRESSION:`-prefixed failure shows up in `run_tests()`'s result
while closing out a cycle: that's something else you touched breaking,
not this feature's own test. Fix it (or ask the user how they want to
handle it) before trying `run_tests()` again — don't treat it as this
cycle's normal RED→IMPLEMENT loop.
