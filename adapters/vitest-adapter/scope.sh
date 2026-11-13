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
  - any file, when such a setup file imports a specifier that is neither
    relative, a Node builtin nor an installed package (an alias) -> null;
  - a file outside the project root -> null.
"""

import fnmatch
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


def config_files(root):
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS and not d.startswith(".")]
        for name in files:
            if any(fnmatch.fnmatch(name, pattern) for pattern in CONFIG_PATTERNS):
                yield os.path.relpath(os.path.join(directory, name), root)


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
    tsconfig path) may name a project file we can't resolve."""
    if specifier.startswith("node:"):
        return True
    parts = specifier.split("/")
    package = "/".join(parts[:2]) if specifier.startswith("@") else parts[0]
    if package in NODE_BUILTINS:
        return True
    directory = os.path.dirname(rel)
    while True:
        if os.path.isdir(os.path.join(root, directory, "node_modules", package)):
            return True
        if not directory:
            return False
        directory = os.path.dirname(directory)


def has_unresolved_import(root, rel):
    return any(
        not specifier.startswith(("./", "../")) and not is_external(root, rel, specifier)
        for specifier in imports(root, rel)
    )


def setup_files(root):
    """Files vite/vitest configs reference (setupFiles, globalSetup, ...)
    and everything they import by relative path, transitively: they run
    around tests without being in any test's import graph.

    A config's relative imports are config modules too (shared or merged
    configs), so their string literals are scanned the same way, resolved
    against the module's directory and the top-level config's; a change to
    one of them is global as well.

    None when a setup file imports something that is neither relative nor
    external: its dependencies can't be known."""
    configs = [(config, os.path.dirname(config)) for config in config_files(root)]
    modules = set()
    pending = []
    while configs:
        module, config_dir = configs.pop()
        if module in modules:
            continue
        modules.add(module)
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


def scope(root, changed):
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
