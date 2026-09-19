import json
import sys

from core import install_agent_configs


def test_installer_configures_cargo_adapter_for_rust_projects(tmp_path, monkeypatch):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "example"\nversion = "0.1.0"\n')
    monkeypatch.setattr(sys, "argv", ["outside-in-tdd-mcp-install", str(tmp_path)])

    install_agent_configs.main()

    config = json.loads((tmp_path / ".tdd-config.json").read_text())
    assert config == {
        "adapter": "cargo-adapter",
        "adapterPath": "cargo-adapter-runner",
        "defaultTestDir": "--workspace",
    }
