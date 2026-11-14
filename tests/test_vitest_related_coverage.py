"""An output-only option added to a `vitest related` suite still runs the
whole suite, so in changed mode it is refused like any other."""

from tests.test_adapter_aware_full_suite_detection import assert_refused


def test_output_options_on_a_related_suite_are_refused(tmp_path):
    assert_refused(
        tmp_path,
        "vitest-adapter",
        "related src/a.ts",
        "related src/a.ts --reporter verbose",
    )
