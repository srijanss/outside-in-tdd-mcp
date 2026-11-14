from mcp import types

from core.server import with_required_params


def tool(description, schema):
    return types.Tool(name="t", description=description, inputSchema=schema)


def test_appends_required_names_or_none_and_leaves_schema_alone():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        "required": ["a", "b"],
    }
    listed = with_required_params(tool("Does a thing.", schema))
    assert listed.description == "Does a thing. Required parameters: a, b."
    assert listed.inputSchema == schema

    bare = with_required_params(tool("Status.", {"type": "object", "properties": {}}))
    assert bare.description == "Status. Required parameters: none."


def test_advertised_tools_carry_the_required_params_suffix():
    from core.server import TOOLS

    for advertised in TOOLS:
        assert "Required parameters:" in (advertised.description or ""), advertised.name
