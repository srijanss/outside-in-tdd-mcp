---
description: Run the current test target N times back-to-back to check for flaky tests, report only fails
argument-hint: [n]
---

Call `run_tests()` "$1" times (default 5 if not given), back-to-back, at
whatever test target is currently active per `get_status()`.

Report only: any test whose pass/fail result changed between runs (name +
how many times it failed out of N). If nothing flaked, say "no flakes in N
runs" and stop. Don't restate passing output or explain the tests.
