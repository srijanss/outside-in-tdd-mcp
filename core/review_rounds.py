import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _load(path: str) -> dict[str, list[dict]]:
    rounds_path = Path(path)
    if not rounds_path.exists():
        return {}
    with rounds_path.open() as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupt review rounds file at {path}: {exc}") from exc
    if not isinstance(data, dict) or not all(
        isinstance(rounds, list) for rounds in data.values()
    ):
        raise ValueError(
            f"Corrupt review rounds file at {path}: must map scopes to lists of rounds"
        )
    return data


def record_round(scope: str, entry: dict, path: str) -> dict:
    rounds_by_scope = _load(path)
    rounds = rounds_by_scope.setdefault(scope, [])
    recorded = {
        **entry,
        "round": len(rounds) + 1,
        "recordedAt": datetime.now(timezone.utc).isoformat(),
    }
    rounds.append(recorded)

    rounds_path = Path(path)
    fd, tmp_path = tempfile.mkstemp(
        dir=rounds_path.parent, prefix=f".{rounds_path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(rounds_by_scope, file)
        os.replace(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise
    return recorded


def list_rounds(scope: str, path: str) -> list[dict]:
    return _load(path).get(scope, [])
