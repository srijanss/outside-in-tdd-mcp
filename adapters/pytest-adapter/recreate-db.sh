#!/usr/bin/env python3
"""Default runner arguments for rebuilding a cached test database.

Usage: recreate-db.sh <project_root>

Prints {"args": "--create-db"} when pytest-django is importable by the
pytest that run.sh would execute, else {"args": null}. Like run.sh, the
project's own .venv/bin/pytest comes first and the PATH pytest second,
skipping one that can't run (not executable, or a shebang interpreter
that doesn't exist here, e.g. a venv built on another platform). The
check imports pytest_django with that pytest's own interpreter, so
system-site-packages, .pth and editable installs all count.
"""

import json
import os
import re
import shutil
import subprocess
import sys

PROBE = (
    "import importlib.util, sys; "
    "sys.exit(0 if importlib.util.find_spec('pytest_django') else 1)"
)
PROBE_TIMEOUT_S = 20
# pip's /bin/sh trampoline, written instead of a plain #! line when the
# interpreter path has spaces or is too long: '''exec' "<python>" "$0" "$@"
TRAMPOLINE = re.compile(r"""^'''exec' (?:"([^"]+)"|(\S+)) "\$0" "\$@"\s*$""")


def pytest_candidates(project_root):
    venv_pytest = os.path.join(project_root, ".venv", "bin", "pytest")
    candidates = [venv_pytest] if os.path.isfile(venv_pytest) else []
    path_pytest = shutil.which("pytest")
    if path_pytest:
        candidates.append(path_pytest)
    return candidates


def shebang(executable):
    """The interpreter argv from an executable script's #! line (or the
    python a pip /bin/sh trampoline execs), or None."""
    if not os.access(executable, os.X_OK):
        return None
    try:
        with open(executable, "rb") as handle:
            first = handle.readline(4096)
            second = handle.readline(4096)
    except OSError:
        return None
    if not first.startswith(b"#!"):
        return None
    argv = first[2:].decode(errors="replace").strip().split(None, 1)
    if argv == ["/bin/sh"]:
        trampoline = TRAMPOLINE.match(second.decode(errors="replace"))
        if trampoline:
            return [trampoline.group(1) or trampoline.group(2)]
    return argv or None


def has_pytest_django(project_root):
    """Whether pytest_django imports for the first pytest that runs, or
    None when no pytest candidate runs at all."""
    for candidate in pytest_candidates(project_root):
        interpreter = shebang(candidate)
        if interpreter is None:
            continue
        try:
            probe = subprocess.run(
                [*interpreter, "-c", PROBE],
                cwd=project_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=PROBE_TIMEOUT_S,
            )
        except OSError:
            continue
        return probe.returncode == 0
    return None


def main():
    project_root = sys.argv[1] if len(sys.argv) > 1 else "."
    args = "--create-db" if has_pytest_django(project_root) else None
    print(json.dumps({"args": args}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
