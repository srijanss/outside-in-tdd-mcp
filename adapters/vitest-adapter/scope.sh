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
  - a file a vite/vitest config references (setupFiles, globalSetup, ...)
    or one such a file imports by relative path, transitively -> null: it
    runs around every test without being imported by one;
  - a file outside the project root -> null.
"""

import fnmatch
import json
import os
import re
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
CONFIG_PATTERNS = (
    "vite.config.*",
    "vitest.config.*",
    "vitest.workspace.*",
    "vitest.projects.*",
)
SKIPPED_DIRS = {"node_modules"}
SOURCE_EXTENSIONS = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
STRING_LITERAL = re.compile(r"""(['"`])([^'"`\\\n]+)\1""")
RELATIVE_IMPORT = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)(['"])(\.{1,2}/[^'"]+)\1"""
)


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


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def resolve(root, base, specifier):
    """Root-relative path of the file ``specifier`` names from ``base``
    (trying the source extensions and ``index`` files), or None."""
    candidate = os.path.normpath(os.path.join(root, base, specifier))
    rel = os.path.relpath(candidate, root)
    if rel == ".." or rel.startswith("../"):
        return None
    for path in (
        candidate,
        *(candidate + ext for ext in SOURCE_EXTENSIONS),
        *(os.path.join(candidate, "index" + ext) for ext in SOURCE_EXTENSIONS),
    ):
        if os.path.isfile(path):
            return os.path.relpath(path, root)
    return None


def config_files(root):
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS and not d.startswith(".")]
        for name in files:
            if any(fnmatch.fnmatch(name, pattern) for pattern in CONFIG_PATTERNS):
                yield os.path.relpath(os.path.join(directory, name), root)


def setup_files(root):
    """Files vite/vitest configs reference (setupFiles, globalSetup, ...)
    and everything they import by relative path, transitively: they run
    around tests without being in any test's import graph."""
    pending = []
    for config in config_files(root):
        base = os.path.dirname(config)
        for _, literal in STRING_LITERAL.findall(read_text(os.path.join(root, config))):
            for directory in {base, ""}:
                found = resolve(root, directory, literal)
                if found and found != config:
                    pending.append(found)
    seen = set()
    while pending:
        rel = pending.pop()
        if rel in seen:
            continue
        seen.add(rel)
        base = os.path.dirname(rel)
        for _, specifier in RELATIVE_IMPORT.findall(read_text(os.path.join(root, rel))):
            found = resolve(root, base, specifier)
            if found:
                pending.append(found)
    return seen


def as_argument(target):
    """Keep a target starting with "-" from parsing as a vitest option."""
    return "./" + target if target.startswith("-") else target


def scope(root, changed):
    targets = set()
    setup = None
    for path in changed:
        rel = os.path.relpath(os.path.join(root, path), root)
        target = target_for(root, rel)
        if target is None:
            return None
        if target:
            if setup is None:
                setup = setup_files(root)
            if target in setup:
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
