import json


def _wrap():
    try:
        json.loads("{")
    except ValueError:
        raise AssertionError("FINAL_ASSERTION_MARKER")


def test_chained_exception():
    _wrap()
