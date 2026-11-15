#!/usr/bin/env python3
"""Map changed files to a vitest regression scope.

Usage: scope.sh <project_root> <changed file>...

Prints {"scope": "related <file>..."} — run.sh turns that into `vitest
related --run <file>...`, which runs only the tests whose import graph
reaches a changed file (a changed test file runs itself) — or
{"scope": null} when the files can't be mapped (the caller then runs the
whole suite):
  - docs (README-, CHANGELOG- or LICENSE-style .md/.rst/.txt names, or
    any .md/.rst/.txt under doc(s)/, at the root or a package root) are
    ignored, as are deleted test files;
  - any other .md/.rst/.txt -> null: it may be a fixture read from disk;
  - package manifests and lockfiles, tsconfig*.json, vite/vitest config,
    workspace and setup files, and dotenv files -> null: they affect tests
    without being imported by them;
  - a deleted non-test file -> null: nothing imports it any more, so its
    former importers can't be found;
  - a file a vite/vitest config references (setupFiles, globalSetup, ...)
    or one such a file imports by relative path, transitively -> null: it
    runs around every test without being imported by one (configs under
    node_modules, dist/build/coverage/out/target, vendor/, tmp/ or dot
    directories aren't searched);
  - any file, when a config module or setup file imports a specifier that
    is neither relative, a Node builtin nor an installed package (an
    alias, or a workspace package linked into node_modules) or a relative
    path naming no file -> null;
  - a file outside the project root -> null.

With TDD_SCOPE_MODE=changed it prints plain paths instead, which run.sh
runs as `vitest run <file>...`: the changed test files that still exist,
plus every test file (*.test.*, *.spec.*, or under __tests__/, skipping
the directories configs aren't searched in) that directly imports a
changed file by relative path (import, export ... from, import(),
require). Transitive importers are not followed. A changed file no test
imports adds nothing; if nothing is added at all it prints
{"scope": null, "empty": true}. Everything above that prints null still
does.

Usage: scope.sh --covers-suite <project_root> <scope> <suite>

Prints {"coversSuite": true} when `vitest run <scope>` runs every test
`vitest run <suite>` runs — output-only options such as --reporter or
--silent are ignored — {"coversSuite": false} when it may run fewer, and
{"coversSuite": null} when either uses an option this script doesn't know.
"""

import fnmatch
import functools
import json
import os
import re
import shlex
import sys

DOC_SUFFIXES = (".md", ".rst", ".txt")
DOC_DIRS = {"doc", "docs"}
DOC_NAMES = {
    "AUTHORS",
    "CHANGELOG",
    "CODE_OF_CONDUCT",
    "CONTRIBUTING",
    "HISTORY",
    "LICENCE",
    "LICENSE",
    "NOTICE",
    "README",
    "SECURITY",
}
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
# Dependencies, build output and caches: never where a project's own
# config lives, and often large.
SKIPPED_DIRS = {
    "build",
    "coverage",
    "dist",
    "node_modules",
    "out",
    "target",
    "tmp",
    "vendor",
}
SOURCE_EXTENSIONS = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
STRING_LITERAL = re.compile(r"""(['"`])([^'"`\\\n]+)\1""")
IMPORT = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)(['"])([^'"\n]+)\1"""
)
# TypeScript sources are imported with the extension they compile to.
COMPILED_EXTENSIONS = {
    ".js": (".ts", ".tsx"),
    ".jsx": (".tsx",),
    ".mjs": (".mts",),
    ".cjs": (".cts",),
}
NODE_BUILTINS = {
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console",
    "constants", "crypto", "dgram", "diagnostics_channel", "dns", "domain",
    "events", "fs", "http", "http2", "https", "inspector", "module", "net",
    "os", "path", "perf_hooks", "process", "punycode", "querystring",
    "readline", "repl", "stream", "string_decoder", "sys", "timers", "tls",
    "trace_events", "tty", "url", "util", "v8", "vm", "wasi",
    "worker_threads", "zlib",
}


def is_test_file(rel):
    name = os.path.basename(rel)
    return (
        any(fnmatch.fnmatch(name, pattern) for pattern in TEST_PATTERNS)
        or "__tests__" in rel.split("/")
    )


def is_package_root(root, directory):
    return not directory or os.path.isfile(os.path.join(root, directory, "package.json"))


def is_documentation(root, rel):
    """A README-style text file at the project root or a package root (a
    directory with a package.json), or a text file under a doc(s)/
    directory there; other text files may be fixtures or raw imports."""
    name = os.path.basename(rel)
    if not name.endswith(DOC_SUFFIXES):
        return False
    parts = rel.split("/")
    if os.path.splitext(name)[0].upper() in DOC_NAMES and is_package_root(
        root, "/".join(parts[:-1])
    ):
        return True
    return any(
        part in DOC_DIRS and is_package_root(root, "/".join(parts[:index]))
        for index, part in enumerate(parts[:-1])
    )


def target_for(root, rel):
    """The related target for ``rel``; "" to skip it, None for no mapping."""
    name = os.path.basename(rel)
    if rel == ".." or rel.startswith("../"):
        return None
    if any(fnmatch.fnmatch(name, pattern) for pattern in GLOBAL_PATTERNS):
        return None
    if is_documentation(root, rel):
        return ""
    if name.endswith(DOC_SUFFIXES):
        return None
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
    (trying the TypeScript source of a .js-style name, the source
    extensions and ``index`` files), or None."""
    candidate = os.path.normpath(os.path.join(root, base, specifier))
    rel = os.path.relpath(candidate, root)
    if rel == ".." or rel.startswith("../"):
        return None
    stem, ext = os.path.splitext(candidate)
    for path in (
        candidate,
        *(stem + source for source in COMPILED_EXTENSIONS.get(ext, ())),
        *(candidate + ext for ext in SOURCE_EXTENSIONS),
        *(os.path.join(candidate, "index" + ext) for ext in SOURCE_EXTENSIONS),
    ):
        if os.path.isfile(path):
            return os.path.relpath(path, root)
    return None


@functools.lru_cache(maxsize=None)
def project_files(root):
    """Every file of the project's own, outside dependencies, build output,
    caches and dot directories (walked once per run)."""
    found = []
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS and not d.startswith(".")]
        for name in files:
            found.append(os.path.relpath(os.path.join(directory, name), root))
    return tuple(found)


def config_files(root):
    for rel in project_files(root):
        name = os.path.basename(rel)
        if any(fnmatch.fnmatch(name, pattern) for pattern in CONFIG_PATTERNS):
            yield rel


@functools.lru_cache(maxsize=None)
def importer_index(root):
    """Root-relative path -> the test files importing it directly by
    relative path (built once per run). Test files whose real location is
    outside the project (a symlink out of it) aren't read."""
    real_root = os.path.realpath(root)
    index = {}
    for rel in project_files(root):
        if not (rel.endswith(SOURCE_EXTENSIONS) and is_test_file(rel)):
            continue
        real = os.path.realpath(os.path.join(root, rel))
        if os.path.commonpath([real_root, real]) != real_root:
            continue
        for found in relative_imports(root, rel):
            index.setdefault(found, set()).add(rel)
    return index


def imports(root, rel):
    text = read_text(os.path.join(root, rel))
    return [specifier for _, specifier in IMPORT.findall(text)]


def relative_imports(root, rel):
    base = os.path.dirname(rel)
    for specifier in imports(root, rel):
        if specifier.startswith(("./", "../")):
            found = resolve(root, base, specifier)
            if found:
                yield found


def is_external(root, rel, specifier):
    """A Node builtin or a package installed in a node_modules directory
    at or above ``rel``'s; anything else (an alias such as "@/x" or a
    tsconfig path) may name a project file we can't resolve. A package
    whose real location is project source (a workspace package linked into
    node_modules) isn't external either."""
    if specifier.startswith("node:"):
        return True
    parts = specifier.split("/")
    package = "/".join(parts[:2]) if specifier.startswith("@") else parts[0]
    if package in NODE_BUILTINS:
        return True
    directory = os.path.dirname(rel)
    while True:
        installed = os.path.join(root, directory, "node_modules", package)
        if os.path.isdir(installed):
            return not is_project_source(root, installed)
        if not directory:
            return False
        directory = os.path.dirname(directory)


def is_project_source(root, path):
    """``path`` really lives inside the project, outside any node_modules."""
    real = os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    parts = real.split(os.sep)
    return parts[0] != ".." and "node_modules" not in parts


def has_unresolved_import(root, rel):
    """An import of ``rel``'s that is an alias, or a relative path naming
    no file (a deleted dependency fails every test the module sets up)."""
    base = os.path.dirname(rel)
    for specifier in imports(root, rel):
        if specifier.startswith(("./", "../")):
            if resolve(root, base, specifier) is None:
                return True
        elif not is_external(root, rel, specifier):
            return True
    return False


def setup_files(root):
    """Files vite/vitest configs reference (setupFiles, globalSetup, ...)
    and everything they import by relative path, transitively: they run
    around tests without being in any test's import graph.

    A config's relative imports are config modules too (shared or merged
    configs), so their string literals are scanned the same way, resolved
    against the module's directory and the top-level config's; a change to
    one of them is global as well.

    None when a config module or setup file imports something that is
    neither relative nor external (an alias), or a relative path that
    names no file: what it brings in can't be known."""
    configs = [(config, os.path.dirname(config)) for config in config_files(root)]
    visited = set()
    modules = set()
    pending = []
    while configs:
        module, config_dir = configs.pop()
        # A module shared by several configs resolves against each one.
        if (module, config_dir) in visited:
            continue
        visited.add((module, config_dir))
        if module not in modules:
            modules.add(module)
            if has_unresolved_import(root, module):
                return None
        imported = set(relative_imports(root, module))
        configs.extend((path, config_dir) for path in imported)
        base = os.path.dirname(module)
        for _, literal in STRING_LITERAL.findall(read_text(os.path.join(root, module))):
            for directory in {base, config_dir}:
                found = resolve(root, directory, literal)
                if found and found not in imported and found != module:
                    pending.append(found)
    seen = set()
    while pending:
        rel = pending.pop()
        if rel not in seen:
            seen.add(rel)
            if has_unresolved_import(root, rel):
                return None
            pending.extend(relative_imports(root, rel))
    # Imported config modules change every test's setup too.
    return seen | modules


def as_argument(target):
    """Keep a target starting with "-" from parsing as a vitest option."""
    return "./" + target if target.startswith("-") else target


def changed_mode():
    return os.environ.get("TDD_SCOPE_MODE") == "changed"


def scope(root, changed, narrow=False):
    """The scope expression; None for no mapping, "" (narrow only) when
    nothing needs to run."""
    targets = set()
    setup = ()
    for path in changed:
        rel = os.path.relpath(os.path.join(root, path), root)
        target = target_for(root, rel)
        if target is None:
            return None
        if target:
            if setup == ():
                setup = setup_files(root)
            if setup is None or target in setup:
                return None
            if not narrow:
                targets.add(target)
                continue
            if is_test_file(target):
                targets.add(target)
            # A changed test may be a helper other tests import.
            targets |= importer_index(root).get(target, set())
    if not targets:
        return "" if narrow else None
    quoted = " ".join(shlex.quote(as_argument(target)) for target in sorted(targets))
    return quoted if narrow else "related " + quoted


# `vitest run` options that only change output, never which tests run.
OUTPUT_FLAGS = {
    "--silent", "--color", "--no-color", "--hideSkippedTests",
    "--logHeapUsage", "--clearScreen", "--no-clearScreen",
}
OUTPUT_VALUE_OPTIONS = {"--reporter", "--outputFile"}
# Options that may change which tests run; any other option is unknown.
SELECTION_FLAGS = {"--changed", "--typecheck", "--passWithNoTests"}
SELECTION_VALUE_OPTIONS = {
    "-t", "--testNamePattern", "--project", "--dir", "--root", "-r", "-c",
    "--config", "--environment", "--shard", "--bail", "--exclude", "--mode",
}


def parse_run(expression):
    """(name filters, selecting options) of ``vitest run <expression>``,
    output-only options dropped. Raises ValueError on an unknown option."""
    filters, options = set(), set()
    tokens = iter(shlex.split(expression))
    for token in tokens:
        if not token.startswith("-"):
            filters.add(token.removeprefix("./").rstrip("/") or ".")
            continue
        name, eq, value = token.partition("=")
        if name in OUTPUT_FLAGS:
            continue
        if name in OUTPUT_VALUE_OPTIONS or name in SELECTION_VALUE_OPTIONS:
            if not eq:
                value = next(tokens, None)
                if value is None:
                    raise ValueError(f"{name} needs a value")
            if name in SELECTION_VALUE_OPTIONS:
                options.add((name, value))
            continue
        if name in SELECTION_FLAGS:
            options.add((name, None))
            continue
        raise ValueError(f"unknown option {token}")
    return filters, options


def split_related(expression):
    """(whether ``expression`` is a ``vitest related`` run, the rest of it)."""
    args = shlex.split(expression)
    if args[:1] == ["related"]:
        return True, shlex.join(args[1:])
    return False, expression


def covers_suite(scope, suite):
    """True when ``vitest run <scope>`` runs every test ``<suite>`` runs,
    False when it may run fewer, None when either can't be parsed.

    Positional arguments are substring filters on test file paths, so a
    scope filter covers a suite filter it is a substring of, and no
    filters at all means every file."""
    try:
        scope_related, scope = split_related(scope)
        suite_related, suite = split_related(suite)
        scope_filters, scope_options = parse_run(scope)
        suite_filters, suite_options = parse_run(suite)
    except ValueError:
        return None
    if not scope_options <= suite_options:
        return False
    if scope_related or suite_related:
        # `vitest related <files>`: the tests importing those files, so a
        # scope covers the suite when it names at least the same files.
        return scope_related and suite_related and scope_filters >= suite_filters
    if not scope_filters:
        return True
    if not suite_filters:
        return False
    return all(
        any(narrow == "." or narrow in wide for narrow in scope_filters)
        for wide in suite_filters
    )


def main(argv):
    if argv[:1] == ["--covers-suite"]:
        if len(argv) != 4:
            return {"coversSuite": None}
        return {"coversSuite": covers_suite(argv[2], argv[3])}
    if len(argv) < 2:
        return {"scope": None}
    result = scope(argv[0], argv[1:], narrow=changed_mode())
    if result == "":
        # Changed mode: nothing beyond the cycle's own target needs to run.
        return {"scope": None, "empty": True}
    return {"scope": result}


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1:])))
