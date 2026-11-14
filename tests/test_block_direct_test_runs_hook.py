"""The scaffolded PreToolUse hook that blocks direct test-runner invocations."""

import json
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / ".agents" / "hooks" / "block-direct-test-runs.sh"


def _decision(command: str) -> str | None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    proc = subprocess.run(
        ["bash", str(HOOK)], input=payload, capture_output=True, text=True, check=True
    )
    out = json.loads(proc.stdout)
    return out.get("hookSpecificOutput", {}).get("permissionDecision")


@pytest.mark.parametrize(
    "command",
    [
        "cargo test",
        "cargo test --workspace",
        "cargo t",
        "cargo +nightly test",
        "RUSTFLAGS=x cargo test",
        "cd x && cargo nextest run",
        "/usr/bin/cargo test -p foo",
        "cargo build; cargo test",
    ],
)
def test_cargo_test_runs_are_denied(command):
    assert _decision(command) == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "cargo build",
        "cargo check --workspace",
        "cargo clippy -- -D warnings",
        "cargo fmt",
        "cargo run --bin x",
        "cargo metadata --format-version 1",
        "cargo tree",
        "cargo +nightly build",
        "cargo test-support",
    ],
)
def test_other_cargo_commands_are_allowed(command):
    assert _decision(command) is None


@pytest.mark.parametrize(
    "command",
    [
        "pytest",
        "uv run pytest tests/",
        "python -m pytest -x",
        "npx vitest run",
        "npm test",
        "go test ./...",
    ],
)
def test_existing_runners_are_still_denied(command):
    assert _decision(command) == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "cargo test; echo done",
        "cargo test&&echo done",
        "cargo t||echo failed",
        "cargo nextest|tee out.log",
        "pytest;echo done",
    ],
)
def test_runner_followed_directly_by_a_separator_is_denied(command):
    assert _decision(command) == "deny"


@pytest.mark.parametrize(
    "template",
    [
        'git commit -m "make {} pass"',
        "echo {}",
        'echo "a; {}"',
    ],
)
def test_mentions_of_cargo_test_match_existing_runner_behaviour(template):
    assert _decision(template.format("cargo test")) == _decision(template.format("pytest"))
