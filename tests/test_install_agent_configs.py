import json
import sys

from core import install_agent_configs


def test_installer_writes_mcpctl_config_from_example_template(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["outside-in-tdd-mcp-install", str(tmp_path)])

    install_agent_configs.main()

    config = json.loads((tmp_path / ".mcp.json").read_text())
    assert config == {
        "mcpServers": {
            "outside-in-tdd": {
                "command": "/usr/local/bin/mcpctl",
                "args": ["run", "outside-in-tdd-mcp"],
            }
        }
    }
    assert not (tmp_path / ".mcp.example.json").exists()


def test_server_entrypoint_install_subcommand_scaffolds_instead_of_serving(
    tmp_path, monkeypatch
):
    from core import server

    monkeypatch.setattr(sys, "argv", ["outside-in-tdd-mcp", "install", str(tmp_path)])

    server.run()

    assert (tmp_path / ".mcp.json").exists()


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
