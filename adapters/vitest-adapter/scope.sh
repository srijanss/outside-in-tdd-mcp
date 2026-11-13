#!/usr/bin/env python3
"""Map changed files to a vitest regression scope.

Usage: scope.sh <project_root> <changed file>...

Prints {"scope": "related <file>..."} — run.sh turns that into `vitest
related --run <file>...`, which runs only the tests whose import graph
reaches a changed file (a changed test file runs itself) — or
{"scope": null} when the files can't be mapped (the caller then runs the
whole suite):
  - docs (.md/.rst/.txt) are ignored, as are deleted test files;
  - package manifests and lockfiles, tsconfig*.json, vite/vitest config,
    workspace and setup files, and dotenv files -> null: they affect tests
    without being imported by them;
  - a deleted non-test file -> null: nothing imports it any more, so its
    former importers can't be found;
  - a file outside the project root -> null.
"""

import fnmatch
import json
import os
import shlex
import sys

DOC_SUFFIXES = (".md", ".rst", ".txt")
GLOBAL_PATTERNS = (
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "bun.lock",
    "bun.lockb",
    "tsconfig*.json",
    "jsconfig*.json",
    "vite.config.*",
    "vitest.config.*",
    "vitest.workspace.*",
    "vitest.setup.*",
    "setupTests.*",
    ".env",
    ".env.*",
)
TEST_PATTERNS = ("*.test.*", "*.spec.*")


def is_test_file(rel):
    name = os.path.basename(rel)
    return (
        any(fnmatch.fnmatch(name, pattern) for pattern in TEST_PATTERNS)
        or "__tests__" in rel.split("/")
    )


def target_for(root, rel):
    """The related target for ``rel``; "" to skip it, None for no mapping."""
    name = os.path.basename(rel)
    if rel == ".." or rel.startswith("../"):
        return None
    if any(fnmatch.fnmatch(name, pattern) for pattern in GLOBAL_PATTERNS):
        return None
    if name.endswith(DOC_SUFFIXES):
        return ""
    if not os.path.exists(os.path.join(root, rel)):
        return "" if is_test_file(rel) else None
    return rel


def as_argument(target):
    """Keep a target starting with "-" from parsing as a vitest option."""
    return "./" + target if target.startswith("-") else target


def scope(root, changed):
    targets = set()
    for path in changed:
        rel = os.path.relpath(os.path.join(root, path), root)
        target = target_for(root, rel)
        if target is None:
            return None
        if target:
            targets.add(target)
    if not targets:
        return None
    return "related " + " ".join(
        shlex.quote(as_argument(target)) for target in sorted(targets)
    )


def main(argv):
    if len(argv) < 2:
        return {"scope": None}
    return {"scope": scope(argv[0], argv[1:])}


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1:])))
