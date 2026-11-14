import anyio
from mcp import types

import core.server as server_module


def listed_tools(tmp_path, monkeypatch) -> list[types.Tool]:
    monkeypatch.setattr(server_module, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(
        server_module, "CONFIG_PATH", str(tmp_path / ".tdd-config.json")
    )
    server = server_module.build_server()
    handler = server.request_handlers[types.ListToolsRequest]
    result = anyio.run(handler, types.ListToolsRequest(method="tools/list"))
    return result.root.tools


def test_every_listed_tool_description_ends_with_its_required_params(
    tmp_path, monkeypatch
):
    tools = listed_tools(tmp_path, monkeypatch)
    assert tools
    for tool in tools:
        required = tool.inputSchema.get("required") or []
        names = ", ".join(required) if required else "none"
        expected = f"Required parameters: {names}."
        assert (tool.description or "").endswith(expected), (
            tool.name,
            tool.description,
        )
