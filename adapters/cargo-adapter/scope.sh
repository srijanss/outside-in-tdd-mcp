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

    pending = list(selected)
    while pending:
        for dependent in dependents[pending.pop()]:
            if dependent not in selected:
                selected.add(dependent)
                pending.append(dependent)
    if not selected:
        return None
    return " ".join(f"-p {shlex.quote(name)}" for name in sorted(selected))


def main(argv):
    if len(argv) < 2:
        return {"scope": None}
    try:
        return {"scope": scope(argv[0], argv[1:])}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # Unreadable or malformed manifests: no mapping.
        return {"scope": None}


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1:])))
