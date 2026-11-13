import pytest

from core.adapter_contract import AdapterError
from core.server import resolve_adapter_timeout


def test_config_value_sets_the_timeout_and_unset_falls_back_to_120():
    assert resolve_adapter_timeout({"adapterTimeoutSeconds": 7}) == 7
    assert resolve_adapter_timeout({}) == 120


def test_env_var_overrides_the_config_value(monkeypatch):
    monkeypatch.setenv("TDD_ADAPTER_TIMEOUT_S", "3")
    assert resolve_adapter_timeout({"adapterTimeoutSeconds": 7}) == 3


def test_max_adapter_timeout_seconds_caps_config_and_env_and_defaults_to_600(
    monkeypatch,
):
    assert resolve_adapter_timeout({"adapterTimeoutSeconds": 5000}) == 600
    assert (
        resolve_adapter_timeout(
            {"adapterTimeoutSeconds": 50, "maxAdapterTimeoutSeconds": 20}
        )
        == 20
    )
    monkeypatch.setenv("TDD_ADAPTER_TIMEOUT_S", "900")
    assert resolve_adapter_timeout({}) == 600


def test_a_non_integer_env_var_is_a_clean_adapter_error(monkeypatch):
    monkeypatch.setenv("TDD_ADAPTER_TIMEOUT_S", "soon")
    with pytest.raises(AdapterError, match="TDD_ADAPTER_TIMEOUT_S must be an integer"):
        resolve_adapter_timeout({})


@pytest.mark.parametrize("field", ["adapterTimeoutSeconds", "maxAdapterTimeoutSeconds"])
@pytest.mark.parametrize("value", ["30", 0, -5, 1.5, True])
def test_load_config_rejects_a_timeout_that_is_not_a_positive_integer(
    tmp_path, field, value
):
    import json

    from core.server import ConfigError, load_config

    path = tmp_path / ".tdd-config.json"
    path.write_text(json.dumps({"adapterPath": "run.sh", field: value}))
    with pytest.raises(ConfigError, match=f"'{field}' must be a positive integer"):
        load_config(str(path))


def test_run_tests_passes_the_resolved_timeout_to_the_adapter(tmp_path, monkeypatch):
    import json

    import core.server as server_module
    from core.adapter_contract import AdapterResult

    seen = []

    def fake_run_adapter(adapter_path, target, project_root, timeout_s=None):
        seen.append(timeout_s)
        return AdapterResult(passed=0, failed=1, duration_ms=1, failures=[], raw_output="")

    monkeypatch.setattr(server_module, "run_adapter", fake_run_adapter)
    adapter = tmp_path / "run.sh"
    adapter.write_text("#!/bin/sh\n")
    adapter.chmod(0o755)
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps({"adapterPath": str(adapter), "adapterTimeoutSeconds": 42})
    )
    server = server_module.TDDServer(
        project_root=str(tmp_path), config_path=str(config_path)
    )
    server.call_tool(
        "init_feature",
        {"featureName": "t", "testFile": "tests/test_t.py", "targetFiles": []},
    )
    server.call_tool("run_tests", {})

    assert seen == [42]
