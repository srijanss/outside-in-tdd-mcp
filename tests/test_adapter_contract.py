import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core.adapter_contract import AdapterError, AdapterResult


def test_from_json_rejects_negative_passed():
    with pytest.raises(AdapterError):
        AdapterResult.from_json({"passed": -1, "failed": 0})


def test_from_json_rejects_negative_failed():
    with pytest.raises(AdapterError):
        AdapterResult.from_json({"passed": 0, "failed": -1})


def test_from_json_rejects_negative_duration_ms():
    with pytest.raises(AdapterError):
        AdapterResult.from_json({"passed": 0, "failed": 0, "duration_ms": -5})
