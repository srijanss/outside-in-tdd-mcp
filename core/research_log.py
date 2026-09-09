"""Append-only log of external research (links read, decisions informed by
them) so it survives a `/clear` or a fresh session instead of living only in
conversation turns. Deliberately separate from `.tdd-session.log`, which
records operational TDD-cycle events, not durable project knowledge."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_PATH = ".tdd-research.json"


def _load(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        with p.open() as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save(path: str, entries: list[dict[str, Any]]) -> None:
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(entries, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except OSError:
        pass  # research log is best-effort; never block the caller


def record_research(
    source: str,
    summary: str,
    related_feature: str | None = None,
    path: str = DEFAULT_PATH,
) -> dict[str, Any]:
    entries = _load(path)
    entry = {
        "date": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "summary": summary,
        "relatedFeature": related_feature,
    }
    entries.append(entry)
    _save(path, entries)
    return entry


def list_research(path: str = DEFAULT_PATH) -> list[dict[str, Any]]:
    return _load(path)
