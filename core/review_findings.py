import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _load(path: str) -> dict[str, list[dict[str, Any]]]:
    review_path = Path(path)
    if not review_path.exists():
        return {}
    with review_path.open() as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupt review findings file at {path}: {exc}") from exc

    if not isinstance(data, dict) or not all(
        isinstance(findings, list)
        and all(isinstance(finding, dict) for finding in findings)
        for findings in data.values()
    ):
        raise ValueError(
            f"Review findings file at {path} must map scopes to lists of findings"
        )
    return data


def record_review_finding(
    scope: str, finding: dict[str, Any], path: str
) -> dict[str, Any]:
    if "id" not in finding:
        raise ValueError("finding must include an 'id'")
    if finding.get("status") in ("rejected", "deferred") and not finding.get("reason"):
        raise ValueError(f"a {finding['status']} finding must include a 'reason'")

    findings_by_scope = _load(path)
    findings = findings_by_scope.setdefault(scope, [])
    previous = next((f for f in findings if f["id"] == finding["id"]), {})
    rejected_count = previous.get("rejectedCount", 0)
    if finding.get("status") == "rejected":
        rejected_count += 1
    if rejected_count:
        finding = {**finding, "rejectedCount": rejected_count}
    findings[:] = [existing for existing in findings if existing["id"] != finding["id"]]
    if finding.get("status") != "fixed":
        findings.append(finding)

    review_path = Path(path)
    fd, tmp_path = tempfile.mkstemp(
        dir=review_path.parent, prefix=f".{review_path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(findings_by_scope, file)
        os.replace(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise
    return finding


def list_review_findings(scope: str, path: str) -> list[dict[str, Any]]:
    return _load(path).get(scope, [])
