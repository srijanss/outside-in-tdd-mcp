#!/usr/bin/env python3
"""Run Cargo tests and translate their output to the TDD adapter contract.

Contract: ./run.sh <test_target> <project_root>
Prints exactly one JSON object to stdout: {passed, failed, duration_ms,
failures, raw_output}. ``test_target`` uses shell-word parsing so callers can
pass Cargo flags and a test-name filter just as they would to ``cargo test``.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path


SUMMARY_RE = re.compile(
    r"test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed;",
)
FAILED_TEST_RE = re.compile(r"^---- (.+) stdout ----$", re.MULTILINE)


def _cargo_command() -> str:
    """Find Cargo even when an MCP client starts with a minimal PATH."""
    configured = os.environ.get("CARGO")
    if configured:
        return configured
    discovered = shutil.which("cargo")
    if discovered:
        return discovered
    standard_install = Path.home() / ".cargo" / "bin" / "cargo"
    return str(standard_install) if standard_install.is_file() else "cargo"


def _failure_messages(raw_output: str) -> list[dict[str, str]]:
    matches = list(FAILED_TEST_RE.finditer(raw_output))
    failures = []
    for index, match in enumerate(matches):
        message_end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_output)
        failures.append(
            {
                "name": match.group(1),
                "message": raw_output[match.end() : message_end].strip()[-500:],
            }
        )
    return failures


SECTION_RE = re.compile(r"^\s*\[([^\]]*)\]\s*(?:#.*)?$")
NAME_RE = re.compile(r"""^\s*name\s*=\s*(?:"([^"]*)"|'([^']*)')\s*(?:#.*)?$""")


def _package_name(manifest: Path) -> str | None:
    """Read ``[package] name`` from a Cargo.toml (no TOML parser on 3.10)."""
    try:
        lines = manifest.read_text().splitlines()
    except OSError:
        return None
    in_package = False
    for line in lines:
        section = SECTION_RE.match(line)
        if section:
            in_package = section.group(1).strip() == "package"
            continue
        name = NAME_RE.match(line) if in_package else None
        if name:
            return name.group(1) or name.group(2) or None
    return None


def _path_to_test_flags(token: str, project_root: str) -> list[str] | None:
    """Map an integration-test file path to ``-p <package> --test <name>``."""
    if not token.endswith(".rs"):
        return None
    path = Path(project_root) / token
    if not path.is_file():
        return None
    parts = Path(token).parts
    if len(parts) >= 3 and parts[-1] == "main.rs" and parts[-3] == "tests":
        test_name, crate_dir = parts[-2], path.parents[2]
    elif len(parts) >= 2 and parts[-2] == "tests":
        test_name, crate_dir = path.stem, path.parents[1]
    else:
        return None
    package = _package_name(crate_dir / "Cargo.toml")
    if package is None:
        return None
    return ["-p", package, "--test", test_name]


def _translate_target(tokens: list[str], project_root: str) -> list[str]:
    translated: list[str] = []
    for index, token in enumerate(tokens):
        if token == "--":
            # Everything after the separator belongs to the test harness.
            translated.extend(tokens[index:])
            break
        flags = _path_to_test_flags(token, project_root)
        translated.extend(flags if flags is not None else [token])
    return translated


def main() -> int:
    test_target = sys.argv[1] if len(sys.argv) > 1 else ""
    project_root = sys.argv[2] if len(sys.argv) > 2 else "."

    start = time.monotonic()
    try:
        proc = subprocess.run(
            [_cargo_command(), "test", *_translate_target(shlex.split(test_target), project_root)],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        raw_output = proc.stdout + proc.stderr
    except OSError as error:
        raw_output = str(error)
        proc = None
    duration_ms = int((time.monotonic() - start) * 1000)

    summaries = SUMMARY_RE.findall(raw_output)
    passed = sum(int(summary[0]) for summary in summaries)
    failed = sum(int(summary[1]) for summary in summaries)
    failures = _failure_messages(raw_output)

    if proc is None or (proc.returncode != 0 and not summaries):
        failed = max(failed, 1)
        failures = [{"name": "cargo", "message": raw_output[-500:]}]

    print(
        json.dumps(
            {
                "passed": passed,
                "failed": failed,
                "duration_ms": duration_ms,
                "failures": failures,
                "raw_output": raw_output[-3000:],
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
