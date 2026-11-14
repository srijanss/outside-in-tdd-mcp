#!/usr/bin/env python3
"""Map changed files to a pytest regression scope.

Usage: scope.sh <project_root> <changed file>...

Prints {"scope": "<space-separated pytest targets>"} or {"scope": null}
when the files can't be mapped (the caller then runs the whole suite):
  - a test file (test_*.py / *_test.py) that still exists is its own target;
  - conftest.py maps to its own directory (null at the project root);
  - pytest config (pyproject.toml, setup.cfg, pytest.ini, tox.ini) and
    dependency manifests (requirements*.txt, constraints*.txt, setup.py,
    *.lock, Pipfile) -> null;
  - docs (.md/.rst/.txt) are ignored;
  - any other file maps to the nearest tests/ directory of its package:
    walking up from its directory, the first directory that is named
    "tests" or contains a "tests/" subdirectory.

With TDD_SCOPE_MODE=changed it prints only the tests closest to the change:
the changed test files that still exist, a changed conftest.py's directory,
and every test file that directly imports a changed .py module (import a.b,
from a.b import x, from a import b, relative imports). Test files are found
under defaultTestDir's directories, else in every tests/ directory; one that
doesn't parse is skipped. Transitive importers and re-exports are not
followed. Other non-.py files add nothing; if nothing is added at all it
prints {"scope": null, "empty": true}. Everything above that prints null
still does.

Usage: scope.sh --covers-suite <project_root> <scope> <suite>

Prints {"coversSuite": true} when running the pytest expression <scope>
runs every test <suite> (defaultTestDir) runs, false when it runs fewer,
null when it can't tell (e.g. an option it doesn't know). Output-only options (-v, -q, -s, --tb, -r,
--capture, --durations, --color, ...) are ignored; any other option of the
scope (a filter such as -k, -m, --deselect, --ignore, -p) must also be in
the suite; each suite path must be named by the scope or sit under a
directory (or file, for a node id) it names.
"""

import ast
import fnmatch
import functools
import json
import os
import shlex
import sys

CONFIG_FILES = {"pyproject.toml", "setup.cfg", "pytest.ini", "tox.ini"}
# Dependency manifests and lock files: a change can break anything.
DEPENDENCY_PATTERNS = (
    "requirements*.txt",
    "constraints*.txt",
    "setup.py",
    "*.lock",
    "Pipfile",
)
DOC_SUFFIXES = (".md", ".rst", ".txt")
SKIP_DIRS = {"node_modules", "__pycache__", "site-packages"}


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


def affects_everything(name):
    """pytest config and dependency manifests: a change can break anything."""
    return name in CONFIG_FILES or any(
        fnmatch.fnmatch(name, pattern) for pattern in DEPENDENCY_PATTERNS
    )


def target_for(root, rel):
    """A pytest target for one changed file; "" to skip it, None if unmappable."""
    rel = os.path.normpath(rel)
    name = os.path.basename(rel)
    rel_dir = os.path.dirname(rel)
    if affects_everything(name):
        return None
    if name.endswith(DOC_SUFFIXES):
        return ""
    if name == "conftest.py":
        return rel_dir or None
    if is_test_file(name):
        return rel if os.path.isfile(os.path.join(root, rel)) else ""
    return nearest_tests_dir(root, rel_dir)


def changed_mode():
    return os.environ.get("TDD_SCOPE_MODE") == "changed"


def module_name(root, rel):
    """The dotted module name of a source file, walking up its packages."""
    stem = os.path.splitext(os.path.basename(rel))[0]
    # A package's __init__.py is the package itself.
    parts = [] if stem == "__init__" else [stem]
    current = os.path.dirname(rel)
    while current and os.path.isfile(os.path.join(root, current, "__init__.py")):
        parts.insert(0, os.path.basename(current))
        current = os.path.dirname(current)
    return ".".join(parts)


def module_names(root, rel):
    """Every name a source file may be imported as: its package name, then
    each longer one through the directories above it, which may be
    namespace packages (no __init__.py) or sys.path entries."""
    parts = os.path.splitext(rel)[0].split(os.sep)
    if parts[-1] == "__init__":
        parts.pop()
    shortest = max(len(module_name(root, rel).split(".")), 1)
    return [
        ".".join(parts[-length:])
        for length in range(shortest, len(parts) + 1)
    ]


def default_test_dirs(root):
    """defaultTestDir's directories inside the project, from the server's
    config (TDD_CONFIG_PATH, else .tdd-config.json); [] when unset."""
    path = os.environ.get("TDD_CONFIG_PATH") or ".tdd-config.json"
    try:
        with open(os.path.join(root, path), encoding="utf-8") as handle:
            value = json.load(handle).get("defaultTestDir")
        entries = shlex.split(value)
    except (OSError, ValueError, AttributeError, TypeError):
        return []
    dirs = []
    for entry in entries:
        rel = os.path.normpath(entry)
        if os.path.isabs(rel) or rel == ".." or rel.startswith("../"):
            continue
        if os.path.isdir(os.path.join(root, rel)):
            dirs.append("" if rel == "." else rel)
    return dirs


def skipped_dir(path):
    """Dot dirs, caches, installed packages and virtualenvs hold no project tests."""
    name = os.path.basename(path)
    return (
        name.startswith(".")
        or name in SKIP_DIRS
        or os.path.isfile(os.path.join(path, "pyvenv.cfg"))
    )


@functools.lru_cache(maxsize=None)
def test_files(root):
    """Test files under defaultTestDir's directories, else every tests/ dir
    (walked once per run)."""
    return tuple(sorted(set(walk_test_files(root))))


def inside(real_root, path):
    """Whether path, symlinks resolved, is inside the (resolved) project root."""
    real = os.path.realpath(path)
    return os.path.commonpath([real_root, real]) == real_root


def walk_test_files(root):
    configured = default_test_dirs(root)
    real_root = os.path.realpath(root)
    for start in configured or [""]:
        if not inside(real_root, os.path.join(root, start)):
            continue  # a symlink out of the project
        for dirpath, dirnames, filenames in os.walk(os.path.join(root, start)):
            dirnames[:] = [
                d for d in dirnames if not skipped_dir(os.path.join(dirpath, d))
            ]
            rel_dir = os.path.relpath(dirpath, root)
            if not configured and "tests" not in rel_dir.split(os.sep):
                continue
            for name in filenames:
                if is_test_file(name) and inside(
                    real_root, os.path.join(dirpath, name)
                ):
                    yield os.path.normpath(os.path.join(rel_dir, name))


@functools.lru_cache(maxsize=None)
def imported_modules(root, rel):
    """Every module name one test file imports (parsed once per run)."""
    try:
        with open(os.path.join(root, rel), encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=rel)
    except (OSError, SyntaxError, ValueError):
        # Unreadable or unparseable: skipped, not a reason to give up.
        return frozenset()
    # The test's own package under each name it may be imported as (its
    # directories above may be namespace packages or sys.path entries).
    packages = [name.split(".")[:-1] for name in module_names(root, rel)]
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            for base in import_bases(node, packages):
                names.add(".".join(base))
                # "from a import b" may import the module a.b.
                names.update(".".join(base + [alias.name]) for alias in node.names)
    return frozenset(names)


def import_bases(node, packages):
    """The absolute module an ImportFrom names, under each candidate package
    of the importing file (one for an absolute import)."""
    if not node.level:
        return [node.module.split(".")]
    bases = []
    for package in packages:
        if node.level > len(package):
            continue  # beyond the top-level package: an ImportError
        base = package[: len(package) - (node.level - 1)]
        bases.append(base + (node.module.split(".") if node.module else []))
    return bases


@functools.lru_cache(maxsize=None)
def importer_index(root):
    """Module name -> the test files importing it or a submodule of it
    (built once per run). Importing a.b.c also runs a.b's (and a's)
    __init__.py, so a.b.c is indexed under a.b.c, a.b and a."""
    index = {}
    for rel in test_files(root):
        for name in imported_modules(root, rel):
            parts = name.split(".")
            for length in range(1, len(parts) + 1):
                index.setdefault(".".join(parts[:length]), set()).add(rel)
    return index


def importers(root, modules):
    index = importer_index(root)
    return set().union(*(index.get(m, ()) for m in modules))


def changed_target_for(root, rel):
    """Changed mode's targets for one changed file; None if unmappable."""
    rel = os.path.normpath(rel)
    name = os.path.basename(rel)
    if name == "conftest.py" or is_test_file(name) or affects_everything(name):
        target = target_for(root, rel)
        if target is None:
            return None
        return {target} if target else set()
    if not name.endswith(".py"):
        return set()
    return importers(root, module_names(root, rel))


def covered(path, dirs):
    return any(path != d and path.startswith(d + "/") for d in dirs)


# Options that only change what pytest prints, never which tests run.
OUTPUT_FLAGS = {
    "-v", "-vv", "-vvv", "--verbose", "-q", "-qq", "--quiet", "-s", "-l",
    "--showlocals", "--no-header", "--no-summary", "--full-trace",
}
OUTPUT_VALUE_OPTIONS = {
    "--tb", "--capture", "--durations", "--durations-min", "--color",
    "--code-highlight", "-r", "--junitxml", "--junit-xml", "--verbosity",
}
# Options taking a value that select or shape the run.
SELECTION_VALUE_OPTIONS = {
    "-k", "-m", "--deselect", "--ignore", "--ignore-glob", "-p", "--maxfail",
    "-c", "--rootdir", "--confcutdir", "-o", "--override-ini",
}
SELECTION_FLAGS = {
    "-x", "--exitfirst", "--lf", "--last-failed", "--ff", "--failed-first",
    "--nf", "--new-first", "--sw", "--stepwise", "--sw-skip",
    "--stepwise-skip", "--runxfail", "--strict-markers",
}


def parse_run(root, expression):
    """A pytest expression's normalised paths and its non-output options."""
    paths, options = [], set()
    tokens = shlex.split(expression)
    i = 0
    while i < len(tokens):
        token = tokens[i]
        i += 1
        if token == "--":
            paths += tokens[i:]
            break
        if not token.startswith("-"):
            paths.append(token)
            continue
        name, has_value, value = token.partition("=")
        if not has_value and len(name) > 2 and name[:2] in (
            OUTPUT_VALUE_OPTIONS | SELECTION_VALUE_OPTIONS
        ):
            name, has_value, value = name[:2], True, name[2:]
        if name in OUTPUT_FLAGS:
            continue
        if name in OUTPUT_VALUE_OPTIONS | SELECTION_VALUE_OPTIONS:
            if not has_value:
                if i >= len(tokens):
                    raise ValueError(f"{name} needs a value")
                value = tokens[i]
                i += 1
            if name in SELECTION_VALUE_OPTIONS:
                options.add((name, value))
            continue
        if name not in SELECTION_FLAGS or has_value:
            # Unknown: it may take a value, so the rest can't be read.
            raise ValueError(f"unknown option {token}")
        options.add(name)
    return [normalise(root, path) for path in paths], options


def normalise(root, path):
    if os.path.isabs(path):
        path = os.path.relpath(path, root)
    return os.path.normpath(path)


def path_covers(scope_path, suite_path):
    return (
        scope_path in (".", suite_path)
        or suite_path.startswith(scope_path + "/")
        or suite_path.startswith(scope_path + "::")
    )


def covers_suite(root, scope, suite):
    try:
        scope_paths, scope_options = parse_run(root, scope)
        suite_paths, suite_options = parse_run(root, suite)
    except ValueError:
        return None
    if not scope_paths or not suite_paths:
        # pytest falls back to testpaths/rootdir, which only config knows.
        return None if scope_paths or suite_paths else scope_options <= suite_options
    if not scope_options <= suite_options:
        return False
    return all(any(path_covers(s, d) for s in scope_paths) for d in suite_paths)


def main(argv):
    if argv[:1] == ["--covers-suite"]:
        if len(argv) != 4:
            return {"coversSuite": None}
        return {"coversSuite": covers_suite(*argv[1:])}
    if len(argv) < 2:
        return {"scope": None}
    root, changed = argv[0], argv[1:]
    targets = set()
    for rel in changed:
        if changed_mode():
            found = changed_target_for(root, rel)
        else:
            target = target_for(root, rel)
            found = None if target is None else {target} - {""}
        if found is None:
            return {"scope": None}
        targets |= found
    dirs = {t for t in targets if os.path.isdir(os.path.join(root, t))}
    kept = sorted(t for t in targets if not covered(t, dirs))
    if not kept:
        # Changed mode: nothing beyond the cycle's own target needs to run.
        return {"scope": None, "empty": True} if changed_mode() else {"scope": None}
    return {"scope": " ".join(shlex.quote(as_argument(t)) for t in kept)}


def as_argument(target):
    """A leading "./" keeps pytest from reading e.g. "--collect-only" as an option."""
    return "./" + target if target.startswith("-") else target


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1:])))
