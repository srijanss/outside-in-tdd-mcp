import re
import subprocess


def _rev_parse(ref: str, repo: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"Unknown revision '{ref}'")
    return result.stdout.strip()


def resolve_review_range(range_spec: str, repo: str) -> dict[str, str]:
    match = re.fullmatch(r"(.+?)\.{2,3}(.+)", range_spec)
    if not match:
        raise ValueError(
            f"Expected a range like '<sha>..HEAD', got '{range_spec}'"
        )
    start_ref, head_ref = match.groups()
    start = _rev_parse(start_ref, repo)
    head = _rev_parse(head_ref, repo)
    is_ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", start, head], cwd=repo
    )
    if is_ancestor.returncode != 0:
        raise ValueError(f"Start commit {start} is not an ancestor of HEAD")
    return {"start": start, "head": head}


MAIN_BRANCH_CANDIDATES = ("main", "master", "origin/main", "origin/master")


def _git(args: list[str], repo: str) -> str | None:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def main_branch(repo: str) -> str | None:
    """The remote's default branch (origin/HEAD) if set, else the first of
    main, master, origin/main and origin/master that exists."""
    remote_head = _git(["symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"], repo)
    for ref in (remote_head, *MAIN_BRANCH_CANDIDATES):
        if ref and _git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], repo):
            return ref
    return None


def default_review_range(repo: str) -> str:
    """'<merge-base with the main branch>..HEAD': the commits this branch
    added."""
    branch = main_branch(repo)
    if branch is None:
        raise ValueError(
            "No range given and no main branch found (tried origin/HEAD, "
            + ", ".join(MAIN_BRANCH_CANDIDATES)
            + ") — pass range='<sha>..HEAD'."
        )
    base = _git(["merge-base", branch, "HEAD"], repo)
    if base is None:
        raise ValueError(f"HEAD shares no history with {branch} — pass range='<sha>..HEAD'.")
    if base == _rev_parse("HEAD", repo):
        raise ValueError(
            f"No new commits since the merge-base with {branch} — commit "
            "work on a branch first, or pass range='<sha>..HEAD'."
        )
    return f"{base}..HEAD"
