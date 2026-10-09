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
