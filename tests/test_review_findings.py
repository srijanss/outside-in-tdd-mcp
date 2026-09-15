import json
from pathlib import Path

from core.server import TDDServer


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_server(tmp_path):
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(
        json.dumps(
            {
                "adapterPath": str(
                    PROJECT_ROOT / "adapters" / "pytest-adapter" / "run.sh"
                )
            }
        )
    )
    return TDDServer(project_root=str(tmp_path), config_path=str(config_path))


def call(server, name, **arguments):
    result = server.call_tool(name, arguments)
    return json.loads(result[0].text)


def test_review_findings_are_shared_by_scope_across_server_instances(tmp_path):
    finder = make_server(tmp_path)
    verifier = make_server(tmp_path)

    recorded = call(
        finder,
        "record_review_finding",
        scope="feature:checkout",
        finding={
            "id": "missing-lock",
            "summary": "Concurrent writes can lose findings",
            "status": "candidate",
        },
    )
    assert recorded["ok"] is True

    call(
        verifier,
        "record_review_finding",
        scope="feature:checkout",
        finding={
            "id": "missing-lock",
            "summary": "Concurrent writes can lose findings",
            "status": "confirmed",
        },
    )

    resumed = call(make_server(tmp_path), "list_review_findings", scope="feature:checkout")

    assert resumed == {
        "scope": "feature:checkout",
        "findings": [
            {
                "id": "missing-lock",
                "summary": "Concurrent writes can lose findings",
                "status": "confirmed",
            }
        ],
    }
