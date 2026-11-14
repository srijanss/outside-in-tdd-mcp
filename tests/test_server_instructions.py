from mcp.server.lowlevel import Server

from core.server import initialization_options


def test_initialization_options_carry_the_default_workflow_instructions():
    options = initialization_options(Server("outside-in-tdd"))

    assert options.server_name == "outside-in-tdd"
    text = (options.instructions or "").lower()
    assert "implement-and-review" in text
    assert "by default" in text
    assert "only when the user names" in text
