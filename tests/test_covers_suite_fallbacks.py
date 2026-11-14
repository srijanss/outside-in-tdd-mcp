"""The server takes the adapter's --covers-suite answer either way, and
falls back to its own path check only when the adapter can't tell: a
missing, legacy, failing or hanging scope.sh, or a null or non-boolean
answer."""

from core.adapter_contract import covers_full_suite
from tests.test_changed_mode_withholds_full_suite import adapter_calls, sweep
from tests.test_covers_full_suite_contract import adapter
from tests.test_server_prefers_adapter_suite_answer import answering_project


def test_an_adapter_false_lets_a_scope_the_core_check_would_refuse_run(tmp_path):
    server = answering_project(tmp_path)
    before = adapter_calls(tmp_path)

    payload = sweep(server, "tests/")

    assert "error" not in payload, payload
    assert len(adapter_calls(tmp_path)) > len(before)


def test_an_unknown_answer_falls_back_to_the_core_check(tmp_path):
    # ANSWERING_SCOPE has no answer for these, so the path check decides:
    # the suite's own path is refused, a -k filter on it runs.
    refused = answering_project(tmp_path / "refused")
    before = adapter_calls(tmp_path / "refused")
    assert "gate" in sweep(refused, "tests").get("error", "")
    assert adapter_calls(tmp_path / "refused") == before

    narrowed = answering_project(tmp_path / "narrowed")
    payload = sweep(narrowed, "tests -k smoke")
    assert "error" not in payload, payload


def test_a_scope_sh_that_cannot_answer_means_unknown(tmp_path):
    bodies = {
        "missing": None,
        "legacy": "#!/bin/sh\necho '{\"scope\": null}'\n",
        "null": "#!/bin/sh\necho '{\"coversSuite\": null}'\n",
        "string": "#!/bin/sh\necho '{\"coversSuite\": \"yes\"}'\n",
        "failing": "#!/bin/sh\necho '{\"coversSuite\": true}'\nexit 3\n",
        "garbage": "#!/bin/sh\necho 'not json'\n",
        "hanging": "#!/bin/sh\nsleep 5\necho '{\"coversSuite\": true}'\n",
    }
    for name, body in bodies.items():
        root = tmp_path / name
        root.mkdir()
        run = adapter(root, body)
        answer = covers_full_suite(run, str(root), "tests -v", "tests", timeout_s=1)
        assert answer is None, name
