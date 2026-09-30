import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core import server


def write_config(tmp_path, data):
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(json.dumps(data))
    return str(config_path)


def test_load_config_raises_clear_error_when_required_key_missing(tmp_path):
    config_path = write_config(
        tmp_path,
        {"adapter": "pytest-adapter", "defaultTestDir": "tests/"},
    )

    with pytest.raises(server.ConfigError, match="adapterPath"):
        server.load_config(config_path)


def test_load_config_raises_when_json_is_invalid(tmp_path):
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text("{not valid json")

    with pytest.raises(server.ConfigError, match="not valid JSON"):
        server.load_config(str(config_path))


def test_load_config_raises_when_top_level_is_not_an_object(tmp_path):
    config_path = tmp_path / ".tdd-config.json"
    config_path.write_text(json.dumps(["adapterPath"]))

    with pytest.raises(server.ConfigError, match="JSON object"):
        server.load_config(str(config_path))


def test_load_config_raises_when_adapter_path_is_empty(tmp_path):
    config_path = write_config(tmp_path, {"adapterPath": ""})

    with pytest.raises(server.ConfigError, match="adapterPath"):
        server.load_config(config_path)


def test_load_config_raises_when_default_test_dir_is_wrong_type(tmp_path):
    config_path = write_config(
        tmp_path, {"adapterPath": "adapters/pytest-adapter/run.sh", "defaultTestDir": 5}
    )

    with pytest.raises(server.ConfigError, match="defaultTestDir"):
        server.load_config(config_path)


def test_load_config_raises_when_recreate_db_args_is_wrong_type(tmp_path):
    config_path = write_config(
        tmp_path,
        {
            "adapterPath": "adapters/pytest-adapter/run.sh",
            "recreateDbArgs": ["--create-db"],
        },
    )

    with pytest.raises(server.ConfigError, match="recreateDbArgs"):
        server.load_config(config_path)


def test_load_config_raises_when_test_name_pattern_is_not_a_valid_regex(tmp_path):
    config_path = write_config(
        tmp_path,
        {"adapterPath": "adapters/pytest-adapter/run.sh", "testNamePattern": "def (test_"},
    )

    with pytest.raises(server.ConfigError, match="testNamePattern"):
        server.load_config(config_path)


def test_load_config_returns_config_when_valid(tmp_path):
    config_path = write_config(
        tmp_path,
        {
            "adapter": "pytest-adapter",
            "adapterPath": "adapters/pytest-adapter/run.sh",
            "defaultTestDir": "tests/",
        },
    )

    config = server.load_config(config_path)

    assert config["adapterPath"] == "adapters/pytest-adapter/run.sh"
