#!/usr/bin/env python3
"""Default runner arguments for rebuilding a cached test database.

Usage: recreate-db.sh <project_root>

Prints {"args": "--create-db"} when the pytest that run.sh would execute
registers pytest-django as a plugin, else {"args": null}. Like run.sh,
the project's own .venv/bin/pytest comes first and the PATH pytest
second, falling back only when one can't be executed at all. The check
asks that pytest itself (`pytest -VV` lists its registered plugins), so
whatever starts it — a #! line, a pip /bin/sh trampoline, a shell
wrapper — and however the plugin is installed, the answer is the one
the test run gets.
"""

import json
import os
import re
import shutil
import subprocess
import sys

PROBE_TIMEOUT_S = 20
# `pytest -VV` lists each registered plugin as "  <name>-<version> at <path>".
PYTEST_DJANGO = re.compile(r"^\s+pytest[-_.]django-\S+ at ", re.IGNORECASE | re.MULTILINE)


def pytest_candidates(project_root):
    venv_pytest = os.path.join(project_root, ".venv", "bin", "pytest")
    candidates = [venv_pytest] if os.path.isfile(venv_pytest) else []
    path_pytest = shutil.which("pytest")
    if path_pytest:
        candidates.append(path_pytest)
    return candidates


def has_pytest_django(project_root):
    """Whether the first pytest that runs registers pytest-django, or None
    when no pytest candidate runs at all (or it hangs)."""
    for candidate in pytest_candidates(project_root):
        try:
            probe = subprocess.run(
                [candidate, "-VV"],
                cwd=project_root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=PROBE_TIMEOUT_S,
            )
        except OSError:
            continue
        except subprocess.TimeoutExpired:
            return None
        return bool(PYTEST_DJANGO.search(probe.stdout + probe.stderr))
    return None


def main():
    project_root = sys.argv[1] if len(sys.argv) > 1 else "."
    args = "--create-db" if has_pytest_django(project_root) else None
    print(json.dumps({"args": args}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
