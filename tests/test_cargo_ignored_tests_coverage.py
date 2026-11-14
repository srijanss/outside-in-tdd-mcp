"""--include-ignored widens a cargo run rather than filtering it, so adding
it to the suite is still the full suite, in changed mode."""

from tests.test_adapter_aware_full_suite_detection import assert_refused


def test_including_ignored_tests_on_the_suite_is_refused(tmp_path):
    assert_refused(
        tmp_path, "cargo-adapter", "--workspace", "--workspace -- --include-ignored"
    )
