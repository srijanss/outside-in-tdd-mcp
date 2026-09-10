---
name: flaky-check
description: Run the current test target N times back-to-back to check for flaky tests, report only fails
---

You have been given an optional N (defaults to 5 if not given).

Call `run_tests()` N times, back-to-back, at whatever test target is
currently active per `get_status()`.

Report only: any test whose pass/fail result changed between runs (name +
how many times it failed out of N). If nothing flaked, say "no flakes in N
runs" and stop. Don't restate passing output or explain the tests.
