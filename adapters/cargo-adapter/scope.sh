#!/usr/bin/env python3
"""Map changed files to a cargo regression scope.

Usage: scope.sh <project_root> <changed file>...

Prints {"scope": "-p <crate> ..."} — one -p per changed crate plus every
workspace crate that depends on it, directly or transitively — or
{"scope": null} when the files can't be mapped (the caller then runs the
whole suite):
  - each file maps to the deepest crate directory containing it; crates are
    the workspace members from the root Cargo.toml (globs and `exclude`
    honored), the root package, if any, and — as cargo does — every path
    dependency of a crate that lies inside the workspace root;
  - the root Cargo.toml, Cargo.lock, .cargo/ and rust-toolchain files -> null;
  - docs (.md/.rst/.txt) are ignored;
  - any other file outside every crate, or an unreadable manifest -> null.

With TDD_SCOPE_MODE=changed it prints -p only for each crate holding a
changed file, without the crates depending on it; docs-only changes print
{"scope": null, "empty": true}. Everything above that prints null still does.

Usage: scope.sh --covers-suite <project_root> <scope> <suite>

Prints {"coversSuite": true} when `cargo test <scope>` runs every test
`cargo test <suite>` runs — output-only options such as --verbose or
`-- --nocapture` are ignored — {"coversSuite": false} when it may run fewer,
and {"coversSuite": null} when either uses an option this script doesn't know.
"""

import glob
import json
import os
import shlex
import sys
import tomllib

DOC_SUFFIXES = (".md", ".rst", ".txt")
GLOBAL_FILES = {"Cargo.toml", "Cargo.lock", "rust-toolchain", "rust-toolchain.toml"}
DEPENDENCY_TABLES = ("dependencies", "dev-dependencies", "build-dependencies")
# scope()'s answer when, in changed mode, nothing beyond the cycle's own
# target needs to run (docs-only changes).
EMPTY = object()


def changed_mode():
    return os.environ.get("TDD_SCOPE_MODE") == "changed"


def load(path):
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def workspace_dependencies(manifest):
    """The root's ``workspace.dependencies`` table."""
    return manifest.get("workspace", {}).get("dependencies", {})


def crate_manifests(root, manifest):
    """Workspace crates as {relative dir: manifest} ("" for the root package).

    Members are those listed in ``workspace.members`` (globs) plus, as in
    cargo, every path dependency of a member that lies inside the workspace
    root — transitively; ``exclude`` prefixes keep a path out of both.
    """
    workspace = manifest.get("workspace", {})
    inherited = workspace_dependencies(manifest)
    excluded = {
        os.path.normpath(path)
        for pattern in workspace.get("exclude", [])
        for path in glob.glob(pattern, root_dir=root)
    }

    def is_member(path):
        return (
            path != ""
            and path != ".."
            and not path.startswith("../")
            and not any(path == e or path.startswith(e + "/") for e in excluded)
            and os.path.isfile(os.path.join(root, path, "Cargo.toml"))
        )

    pending = [""] if "package" in manifest else []
    for pattern in workspace.get("members", []):
        for path in glob.glob(pattern, root_dir=root):
            path = os.path.normpath(path)
            if is_member(path):
                pending.append(path)
    crates = {}
    while pending:
        crate = pending.pop()
        if crate in crates:
            continue
        crates[crate] = (
            manifest if crate == "" else load(os.path.join(root, crate, "Cargo.toml"))
        )
        for path in path_dependencies(root, crate, crates[crate], inherited):
            if path not in crates and is_member(path):
                pending.append(path)
    return crates


def dependency_specs(manifest, inherited):
    """(key, spec, from_root) per dependency; ``{ workspace = true }``
    entries are resolved against the root's ``workspace.dependencies``,
    whose paths are relative to the root (``from_root``)."""
    tables = [manifest.get(name, {}) for name in DEPENDENCY_TABLES]
    for target in manifest.get("target", {}).values():
        tables.extend(target.get(name, {}) for name in DEPENDENCY_TABLES)
    for table in tables:
        for key, spec in table.items():
            if isinstance(spec, dict) and spec.get("workspace") is True:
                yield key, inherited[key], True
            else:
                yield key, spec, False


def dependency_names(manifest, inherited):
    """Crate names ``manifest`` depends on, honoring ``package`` renames."""
    for key, spec, _ in dependency_specs(manifest, inherited):
        if isinstance(spec, dict) and isinstance(spec.get("package"), str):
            yield spec["package"]
        else:
            yield key


def path_dependencies(root, crate, manifest, inherited):
    """Root-relative directories of ``manifest``'s path dependencies."""
    for _, spec, from_root in dependency_specs(manifest, inherited):
        if isinstance(spec, dict) and isinstance(spec.get("path"), str):
            base = os.path.join(root, "" if from_root else crate)
            path = os.path.relpath(os.path.join(base, spec["path"]), root)
            yield "" if path == "." else path


def owning_crate(rel, dirs):
    best = None
    for crate in dirs:
        inside = crate == "" or rel == crate or rel.startswith(crate + "/")
        if inside and (best is None or len(crate) > len(best)):
            best = crate
    return best


def scope(root, changed):
    root_manifest = os.path.join(root, "Cargo.toml")
    if not os.path.isfile(root_manifest):
        return None
    manifest = load(root_manifest)
    manifests = crate_manifests(root, manifest)
    dirs = set(manifests)
    names = {crate: manifests[crate]["package"]["name"] for crate in dirs}
    workspace_names = set(names.values())
    dependents = {name: set() for name in workspace_names}
    inherited = workspace_dependencies(manifest)
    for crate in dirs:
        for dependency in dependency_names(manifests[crate], inherited):
            if dependency in workspace_names:
                dependents[dependency].add(names[crate])

    selected = set()
    for rel in changed:
        rel = os.path.normpath(rel)
        name = os.path.basename(rel)
        if rel in GLOBAL_FILES or rel == ".cargo" or rel.startswith(".cargo/"):
            return None
        if name.endswith(DOC_SUFFIXES):
            continue
        crate = owning_crate(rel, dirs)
        if crate is None:
            return None
        selected.add(names[crate])

    # Changed mode: only the changed crates, not their dependents.
    pending = [] if changed_mode() else list(selected)
    while pending:
        for dependent in dependents[pending.pop()]:
            if dependent not in selected:
                selected.add(dependent)
                pending.append(dependent)
    if not selected:
        return EMPTY if changed_mode() else None
    return " ".join(f"-p {shlex.quote(name)}" for name in sorted(selected))


# `cargo test` options that only change output, never which tests run —
# before `--` (cargo's own) and after it (the libtest harness's).
CARGO_OUTPUT_FLAGS = {"-v", "-vv", "--verbose", "-q", "--quiet"}
CARGO_OUTPUT_VALUE_OPTIONS = {"--color", "--message-format", "-j", "--jobs"}
HARNESS_OUTPUT_FLAGS = {"--nocapture", "--show-output", "-q", "--quiet"}
HARNESS_OUTPUT_VALUE_OPTIONS = {"--color", "--test-threads", "--format"}
# Options that may change which tests run. Anything in neither table is
# unknown, so the whole answer is unknown.
CARGO_SELECTION_FLAGS = {
    "--workspace", "--all", "--lib", "--bins", "--tests", "--examples",
    "--benches", "--doc", "--all-targets", "--all-features",
    "--no-default-features", "--release", "--no-fail-fast",
}
CARGO_SELECTION_VALUE_OPTIONS = {
    "-p", "--package", "--exclude", "--bin", "--test", "--example", "--bench",
    "-F", "--features", "--target", "--profile", "--manifest-path",
}
HARNESS_SELECTION_FLAGS = {"--exact", "--ignored", "--include-ignored"}
HARNESS_SELECTION_VALUE_OPTIONS = {"--skip"}
ALIASES = {"--package": "-p", "--all": "--workspace", "--features": "-F"}
PACKAGE_SELECTION = {"-p", "--workspace", "--exclude"}


def parse_run(expression):
    """The test-selecting part of ``cargo test <expression>`` as a set of
    (side, option, value) tuples — side "cargo" or "harness" (after
    ``--``), option None for a name filter — with output-only options
    dropped. Raises ValueError on an option it doesn't know."""
    selection = set()
    side = "cargo"
    tokens = iter(shlex.split(expression))
    for token in tokens:
        if token == "--" and side == "cargo":
            side = "harness"
            continue
        if not token.startswith("-"):
            selection.add((side, None, token))
            continue
        harness = side == "harness"
        name, eq, value = token.partition("=")
        if not eq and not token.startswith("--") and len(token) > 2:
            name, value, eq = token[:2], token[2:], "attached"
        if name in (HARNESS_OUTPUT_FLAGS if harness else CARGO_OUTPUT_FLAGS):
            continue
        output = HARNESS_OUTPUT_VALUE_OPTIONS if harness else CARGO_OUTPUT_VALUE_OPTIONS
        selecting = (
            HARNESS_SELECTION_VALUE_OPTIONS if harness else CARGO_SELECTION_VALUE_OPTIONS
        )
        if name in output or name in selecting:
            if not eq:
                value = next(tokens, None)
                if value is None:
                    raise ValueError(f"{name} needs a value")
            if name in selecting:
                selection.add((side, ALIASES.get(name, name), value))
            continue
        if name in (HARNESS_SELECTION_FLAGS if harness else CARGO_SELECTION_FLAGS):
            selection.add((side, ALIASES.get(name, name), None))
            continue
        raise ValueError(f"unknown option {token}")
    return selection


def packages_cover(scope, suite):
    """Whether the packages ``scope`` selects include all of ``suite``'s."""
    if scope == suite:
        return True
    if ("cargo", "--workspace", None) in scope:
        return not any(option == "--exclude" for _, option, _ in scope)
    only_packages = all(option == "-p" for _, option, _ in scope | suite)
    return bool(scope) and bool(suite) and only_packages and suite <= scope


def covers_suite(scope, suite):
    """True when ``cargo test <scope>`` runs every test ``<suite>`` runs,
    False when it may run fewer, None when either can't be parsed."""
    try:
        scope_run, suite_run = parse_run(scope), parse_run(suite)
    except ValueError:
        return None

    def split(run):
        packages = {entry for entry in run if entry[1] in PACKAGE_SELECTION}
        return packages, run - packages

    scope_packages, scope_rest = split(scope_run)
    suite_packages, suite_rest = split(suite_run)
    # Every other selecting option narrows the run, so the scope may only
    # use ones the suite uses too.
    return scope_rest <= suite_rest and packages_cover(scope_packages, suite_packages)


def main(argv):
    if argv[:1] == ["--covers-suite"]:
        if len(argv) != 4:
            return {"coversSuite": None}
        return {"coversSuite": covers_suite(argv[2], argv[3])}
    if len(argv) < 2:
        return {"scope": None}
    try:
        result = scope(argv[0], argv[1:])
        if result is EMPTY:
            return {"scope": None, "empty": True}
        return {"scope": result}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # Unreadable or malformed manifests: no mapping.
        return {"scope": None}


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1:])))
