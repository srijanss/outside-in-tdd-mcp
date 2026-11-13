import re


class ReviewerConfigError(ValueError):
    pass


class ReviewerProcessError(RuntimeError):
    """The reviewer process failed without producing any output."""


# Isolation: no session, no MCP (the reviewer must not reach this server),
# no extensions/skills/prompt templates/context files (AGENTS.md is written
# for the implementer), and only the read tool (no bash/edit/write).
REVIEWERS = ("pi", "claude")
THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")

PI_BASE_ARGV = [
    "pi", "-p", "--mode", "json", "--no-session",
    "--no-mcp", "--no-extensions", "--no-skills",
    "--no-prompt-templates", "--no-context-files",
    "--tools", "read",
]

# Headless Claude Code: no session, read-only (Read is the only tool), no
# MCP servers and no user/project settings, so it can't reach this server.
CLAUDE_BASE_ARGV = [
    "claude", "-p", "--output-format", "json", "--no-session-persistence",
    "--restricted", "--strict-mcp-config", "--tools", "Read",
]
# Claude Code has no "off"/"minimal"; map them to the nearest option.
CLAUDE_EFFORT = {"off": None, "minimal": "low"}


def build_reviewer_command(
    prompt: str,
    reviewer: str | None = None,
    model: str | None = None,
    thinking: str | None = None,
    config: dict | None = None,
) -> dict:
    defaults = ((config or {}).get("reviewers") or {}).get("default") or {}
    reviewer = reviewer or defaults.get("reviewer") or "pi"
    model = model or defaults.get("model")
    thinking = thinking or defaults.get("thinking")

    if reviewer not in REVIEWERS:
        raise ReviewerConfigError(f"Unknown reviewer '{reviewer}'")
    for name, value in (("model", model), ("thinking", thinking)):
        if value and value.startswith("-"):
            raise ReviewerConfigError(f"{name} must not start with '-': '{value}'")
    if thinking and thinking not in THINKING_LEVELS:
        raise ReviewerConfigError(f"Unknown thinking level '{thinking}'")
    allowed = (config or {}).get("reviewers", {}).get("allowedModels")
    if model and allowed and model not in allowed:
        raise ReviewerConfigError(f"Model '{model}' is not in allowedModels")

    if reviewer == "claude":
        argv = list(CLAUDE_BASE_ARGV)
        effort = CLAUDE_EFFORT.get(thinking, thinking)
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--effort", effort]
    else:
        argv = list(PI_BASE_ARGV)
        if model:
            argv += ["--model", model]
        if thinking:
            argv += ["--thinking", thinking]
    # The prompt carries the whole diff, which can exceed the OS limit for a
    # single argv element (E2BIG), so it travels on stdin; both reviewers
    # read the prompt from piped stdin in print mode.
    return {
        "reviewer": reviewer,
        "model": model,
        "thinking": thinking,
        "argv": argv,
        "stdin": prompt,
    }


# Provider phrasings meaning the model can't serve this caller right now
# (quota, rate limit, billing, auth/model access), not a problem with the
# review itself. Only matched against errors the reviewer reported.
QUOTA_OR_ACCESS_ERROR = re.compile(
    r"quota|rate.?limit|too many requests|\b429\b|\b40[13]\b|"
    r"unauthori[sz]ed|forbidden|billing|credit balance|out of credits|"
    r"usage.?limit|invalid.?api.?key|"
    r"(?:no|denied|lacks?|does not have|doesn't have|don't have) access to (?:the )?model|"
    r"model\b[^.]*\bnot (?:available|enabled|allowed)",
    re.IGNORECASE,
)


def is_quota_or_access_error(message: str) -> bool:
    return bool(QUOTA_OR_ACCESS_ERROR.search(message))


def fallback_models(config: dict | None, model: str | None) -> list[str]:
    """reviewers.fallbackModels to try, in order, after ``model`` fails on a
    quota/access error: itself and models outside allowedModels skipped."""
    reviewers = (config or {}).get("reviewers") or {}
    allowed = reviewers.get("allowedModels")
    fallbacks = []
    for candidate in reviewers.get("fallbackModels") or []:
        if candidate == model or candidate in fallbacks:
            continue
        if allowed and candidate not in allowed:
            continue
        fallbacks.append(candidate)
    return fallbacks
