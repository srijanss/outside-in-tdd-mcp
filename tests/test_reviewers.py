import pytest

from core.reviewers import ReviewerConfigError, build_reviewer_command


def test_pi_command_is_an_isolated_read_only_argv_with_the_prompt_after_double_dash():
    command = build_reviewer_command(
        "review this",
        reviewer="pi",
        model="openai/gpt-6.1-sol",
        thinking="medium",
        config={},
    )

    assert command == {
        "reviewer": "pi",
        "model": "openai/gpt-6.1-sol",
        "thinking": "medium",
        "argv": [
            "pi", "-p", "--mode", "json", "--no-session",
            "--no-mcp", "--no-extensions", "--no-skills",
            "--no-prompt-templates", "--no-context-files",
            "--tools", "read",
            "--model", "openai/gpt-6.1-sol",
            "--thinking", "medium",
            "--", "review this",
        ],
    }


CONFIG = {
    "reviewers": {
        "default": {"reviewer": "pi", "model": "openai/m-default", "thinking": "low"}
    }
}


def flag_value(argv, flag):
    return argv[argv.index(flag) + 1] if flag in argv else None


def test_values_resolve_per_call_then_config_default_then_the_tools_own_default():
    from_config = build_reviewer_command("p", config=CONFIG)
    assert (from_config["reviewer"], from_config["model"], from_config["thinking"]) == (
        "pi", "openai/m-default", "low",
    )

    overridden = build_reviewer_command("p", model="openai/m-call", config=CONFIG)
    assert flag_value(overridden["argv"], "--model") == "openai/m-call"
    assert flag_value(overridden["argv"], "--thinking") == "low"

    bare = build_reviewer_command("p", config={})
    assert bare["reviewer"] == "pi"
    assert bare["model"] is None and bare["thinking"] is None
    assert "--model" not in bare["argv"] and "--thinking" not in bare["argv"]


@pytest.mark.parametrize(
    "kwargs, config, message",
    [
        ({"reviewer": "gemini"}, {}, "Unknown reviewer 'gemini'"),
        (
            {"model": "openai/other"},
            {"reviewers": {"allowedModels": ["openai/ok"]}},
            "Model 'openai/other' is not in allowedModels",
        ),
        ({"thinking": "extreme"}, {}, "Unknown thinking level 'extreme'"),
        ({"model": "--no-mcp"}, {}, "must not start with '-'"),
        ({"thinking": "-x"}, {}, "must not start with '-'"),
    ],
)
def test_invalid_reviewer_model_or_thinking_is_rejected_before_building_a_command(
    kwargs, config, message
):
    with pytest.raises(ReviewerConfigError, match=message):
        build_reviewer_command("p", config=config, **kwargs)


def test_an_allowlisted_model_is_accepted():
    config = {"reviewers": {"allowedModels": ["openai/ok"]}}

    command = build_reviewer_command("p", model="openai/ok", config=config)

    assert command["model"] == "openai/ok"


def test_claude_command_is_headless_read_only_and_isolated_with_model_and_effort():
    command = build_reviewer_command(
        "PROMPT", reviewer="claude", model="opus", thinking="high"
    )

    argv = command["argv"]
    assert command["reviewer"] == "claude"
    assert argv[:2] == ["claude", "-p"]
    for flag in ("--no-session-persistence", "--restricted", "--strict-mcp-config"):
        assert flag in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--tools") + 1] == "Read"
    assert argv[argv.index("--model") + 1] == "opus"
    assert argv[argv.index("--effort") + 1] == "high"
    assert argv[-2:] == ["--", "PROMPT"]


def test_claude_effort_maps_pi_style_thinking_levels_to_the_nearest_option():
    def argv(thinking):
        return build_reviewer_command(
            "P", reviewer="claude", thinking=thinking
        )["argv"]

    assert "--effort" not in argv("off")
    assert "--effort" not in argv(None)
    assert argv("minimal")[argv("minimal").index("--effort") + 1] == "low"
    assert argv("xhigh")[argv("xhigh").index("--effort") + 1] == "xhigh"
