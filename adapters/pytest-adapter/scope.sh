#!/usr/bin/env python3
"""Map changed files to a pytest regression scope.

Usage: scope.sh <project_root> <changed file>...

Prints {"scope": "<space-separated pytest targets>"} or {"scope": null}
when the files can't be mapped (the caller then runs the whole suite):
  - a test file (test_*.py / *_test.py) that still exists is its own target;
  - conftest.py maps to its own directory (null at the project root);
  - pytest config (pyproject.toml, setup.cfg, pytest.ini, tox.ini) -> null;
  - docs (.md/.rst/.txt) are ignored;
  - any other file maps to the nearest tests/ directory of its package:
    walking up from its directory, the first directory that is named
    "tests" or contains a "tests/" subdirectory.
"""

import json
import os
import shlex
import sys

CONFIG_FILES = {"pyproject.toml", "setup.cfg", "pytest.ini", "tox.ini"}
DOC_SUFFIXES = (".md", ".rst", ".txt")


def is_test_file(name):
    return name.endswith(".py") and (
        name.startswith("test_") or name.endswith("_test.py")
    )


def nearest_tests_dir(root, rel_dir):
    current = rel_dir
    while True:
        if os.path.basename(current) == "tests":
            return current
        candidate = os.path.join(current, "tests") if current else "tests"
        if os.path.isdir(os.path.join(root, candidate)):
            return candidate
        if not current:
            return None
        current = os.path.dirname(current)


def target_for(root, rel):
    """A pytest target for one changed file; "" to skip it, None if unmappable."""
    rel = os.path.normpath(rel)
    name = os.path.basename(rel)
    rel_dir = os.path.dirname(rel)
    if name in CONFIG_FILES:
        return None
    if name.endswith(DOC_SUFFIXES):
        return ""
    if name == "conftest.py":
        return rel_dir or None
    if is_test_file(name):
        return rel if os.path.isfile(os.path.join(root, rel)) else ""
    return nearest_tests_dir(root, rel_dir)


def covered(path, dirs):
    return any(path != d and path.startswith(d + "/") for d in dirs)


def main(argv):
    if len(argv) < 2:
        return {"scope": None}
    root, changed = argv[0], argv[1:]
    targets = set()
    for rel in changed:
        target = target_for(root, rel)
        if target is None:
            return {"scope": None}
        if target:
            targets.add(target)
    dirs = {t for t in targets if os.path.isdir(os.path.join(root, t))}
    kept = sorted(t for t in targets if not covered(t, dirs))
    if not kept:
        return {"scope": None}
    return {"scope": " ".join(shlex.quote(t) for t in kept)}


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1:])))
