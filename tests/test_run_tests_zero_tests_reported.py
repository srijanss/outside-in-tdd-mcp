import json
from pathlib import Path

from core.server import TDDServer


def _server(tmp_path: Path) -> TDDServer:
    adapter = tmp_path / "fake_adapter.py"
    adapter.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        'print(json.dumps({"passed": 0, "failed": 0, "failures": []}))\n'
    )
    adapter.chmod(0o755)
    config = tmp_path / ".tdd-config.json"
    config.write_text(json.dumps({"adapterPath": str(adapter)}))
    return TDDServer(project_root=str(tmp_path), config_path=str(config))


def _call(server, name, **arguments):
    return json.loads(server.call_tool(name, arguments)[0].text)


def test_zero_tests_sets_no_tests_ran_last_error(tmp_path):
    server = _server(tmp_path)
    _call(server, "init_feature", featureName="f", testFile="t.py", targetFiles=[])

    payload = _call(server, "run_tests")

    assert payload["lastError"] == "No tests ran for target t.py"
    assert payload["phase"] == "red"
    assert payload["testResult"]["passed"] == 0
