import json
import subprocess
from pathlib import Path

from core.server import TDDServer


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _server(tmp_path: Path, branch: str | None = "feat-a", ledger=None) -> TDDServer:
    adapter = tmp_path / "fake_adapter.py"
    adapter.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        'print(json.dumps({"passed": 0, "failed": 0, "failures": []}))\n'
    )
    adapter.chmod(0o755)
    config = tmp_path / ".tdd-config.json"
    config.write_text(json.dumps({"adapterPath": str(adapter)}))
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(
        tmp_path,
        "-c", "user.name=t", "-c", "user.email=t@t",
        "commit", "-q", "--allow-empty", "-m", "init",
    )
    if branch is None:
        _git(tmp_path, "checkout", "-q", "--detach")
    elif branch != "main":
        _git(tmp_path, "checkout", "-q", "-b", branch)
    (tmp_path / ".tdd-features.json").write_text(json.dumps(ledger or _ledger()))
    return TDDServer(project_root=str(tmp_path), config_path=str(config))


def _ledger(dep_extra=None):
    dep = {
        "featureName": "dep",
        "dependsOn": [],
        "status": "awaiting_delivery",
        "heldOn": "feat-a",
    }
    dep.update(dep_extra or {})
    return [dep, {"featureName": "next", "dependsOn": ["dep"], "status": "pending"}]


def _call(server, name, **arguments):
    return json.loads(server.call_tool(name, arguments)[0].text)


def _init(server, name="next"):
    return _call(server, "init_feature", featureName=name, testFile="t.py", targetFiles=[])


def test_dependency_awaiting_delivery_on_current_branch_is_met(tmp_path):
    server = _server(tmp_path, branch="feat-a")

    payload = _init(server)

    assert "error" not in payload
    assert payload["featureName"] == "next"


def test_dependency_awaiting_delivery_on_other_branch_is_refused(tmp_path):
    server = _server(tmp_path, branch="feat-b")

    payload = _init(server)

    assert payload["error"].count("dep is built on feat-a, awaiting delivery") == 1


def test_dependency_awaiting_delivery_without_held_on_is_refused(tmp_path):
    server = _server(tmp_path, ledger=_ledger({"heldOn": None}))

    payload = _init(server)

    assert "dep is built, awaiting delivery" in payload["error"]


def test_dependency_awaiting_delivery_on_detached_head_is_refused(tmp_path):
    server = _server(tmp_path, branch=None)

    payload = _init(server)

    assert "dep is built on feat-a, awaiting delivery" in payload["error"]


def test_init_on_awaiting_delivery_feature_is_refused(tmp_path):
    server = _server(tmp_path)

    payload = _init(server, "dep")

    assert "already built on feat-a, awaiting delivery" in payload["error"]


def test_complete_on_awaiting_delivery_feature_is_refused(tmp_path):
    server = _server(tmp_path)
    _init(server)
    _set_status(tmp_path, "next", "awaiting_delivery", "feat-a")

    payload = _call(server, "complete_feature")

    assert "already built on feat-a, awaiting delivery" in payload["error"]
    assert _status_of(tmp_path, "next") == "awaiting_delivery"


def test_reset_on_awaiting_delivery_feature_is_refused(tmp_path):
    server = _server(tmp_path)
    _init(server)
    _set_status(tmp_path, "next", "awaiting_delivery", "feat-a")

    payload = _call(server, "reset_feature")

    assert "already built on feat-a, awaiting delivery" in payload["error"]
    assert _status_of(tmp_path, "next") == "awaiting_delivery"


def _set_status(root, name, status, held_on):
    path = root / ".tdd-features.json"
    features = json.loads(path.read_text())
    for f in features:
        if f["featureName"] == name:
            f["status"] = status
            f["heldOn"] = held_on
    path.write_text(json.dumps(features))


def _status_of(root, name):
    features = json.loads((root / ".tdd-features.json").read_text())
    return next(f["status"] for f in features if f["featureName"] == name)


def test_list_features_shows_awaiting_status_and_branch_not_counted_completed(tmp_path):
    server = _server(tmp_path)

    payload = _call(server, "list_features")

    dep = next(f for f in payload["features"] if f["featureName"] == "dep")
    assert dep["status"] == "awaiting_delivery" and dep["heldOn"] == "feat-a"
    assert payload["completedFeatureCount"] == 0


def test_get_status_shows_awaiting_delivery_features_and_branch(tmp_path):
    server = _server(tmp_path)

    payload = _call(server, "get_status")

    assert payload["awaitingDelivery"] == [
        {"featureName": "dep", "heldOn": "feat-a"}
    ]


def test_remove_completed_features_keeps_awaiting_delivery(tmp_path):
    server = _server(tmp_path)

    _call(server, "remove_completed_features")

    assert _status_of(tmp_path, "dep") == "awaiting_delivery"
