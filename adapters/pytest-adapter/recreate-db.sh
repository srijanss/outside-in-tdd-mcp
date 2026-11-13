#!/usr/bin/env python3
"""Default runner arguments for rebuilding a cached test database.

Usage: recreate-db.sh <project_root>

Prints {"args": "--create-db"} when pytest-django is installed for the
pytest the adapter will run, else {"args": null}. Like run.sh, the
project's own .venv wins when it has a pytest; otherwise this checks the
Python running this script (the one whose pytest is on PATH in the
usual setups).
"""

import glob
import importlib.util
import json
import os
import sys


def has_pytest_django(project_root):
    venv = os.path.join(project_root, ".venv")
    if os.path.isfile(os.path.join(venv, "bin", "pytest")):
        pattern = os.path.join(
            venv, "lib*", "python*", "site-packages", "pytest_django"
        )
        return any(os.path.isdir(path) for path in glob.glob(pattern))
    return importlib.util.find_spec("pytest_django") is not None


def main():
    project_root = sys.argv[1] if len(sys.argv) > 1 else "."
    args = "--create-db" if has_pytest_django(project_root) else None
    print(json.dumps({"args": args}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
