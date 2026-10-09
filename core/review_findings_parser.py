import json
import re

SEVERITIES = ("low", "medium", "high", "critical")
STRING_FIELDS = ("id", "file", "claim", "suggestion")


class FindingsParseError(ValueError):
    pass


def _validate_finding(index: int, finding: object) -> None:
    if not isinstance(finding, dict):
        raise FindingsParseError(f"finding #{index} must be an object")
    for field in STRING_FIELDS:
        value = finding.get(field)
        if not isinstance(value, str) or not value:
            raise FindingsParseError(
                f"finding #{index}: '{field}' must be a non-empty string"
            )
    if finding.get("severity") not in SEVERITIES:
        raise FindingsParseError(
            f"finding #{index}: 'severity' must be one of {', '.join(SEVERITIES)}"
        )
    line = finding.get("line")
    if not isinstance(line, int) or isinstance(line, bool):
        raise FindingsParseError(f"finding #{index}: 'line' must be an integer")


def parse_findings(text: str) -> list[dict]:
    blocks = re.findall(r"```json\s*(.*?)```", text, re.DOTALL)
    if not blocks:
        raise FindingsParseError("No ```json findings block found in reviewer output")
    try:
        payload = json.loads(blocks[-1])
    except json.JSONDecodeError as exc:
        raise FindingsParseError(f"Findings block is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("findings"), list):
        raise FindingsParseError("Findings JSON must be an object with a 'findings' list")
    for index, finding in enumerate(payload["findings"]):
        _validate_finding(index, finding)
    return payload["findings"]
