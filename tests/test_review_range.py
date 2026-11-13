import subprocess

import pytest

from core.review_range import default_review_range, resolve_review_range


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo, name):
    (repo / name).write_text(name)
    git(repo, "add", name)
    git(
        repo,
        "-c", "user.name=t",
        "-c", "user.email=t@example.com",
        "commit", "-q", "-m", name,
    )
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    return tmp_path


def test_resolves_a_sha_to_head_range_into_full_start_and_head_shas(repo):
    first = commit(repo, "a")
    head = commit(repo, "b")

    resolved = resolve_review_range(f"{first[:8]}..HEAD", repo=str(repo))

    assert resolved == {"start": first, "head": head}


def test_rejects_a_start_sha_that_does_not_exist(repo):
    commit(repo, "a")

    with pytest.raises(ValueError, match="Unknown revision 'deadbeef'"):
        resolve_review_range("deadbeef..HEAD", repo=str(repo))


def test_rejects_a_start_commit_that_is_not_an_ancestor_of_head(repo):
    commit(repo, "a")
    git(repo, "checkout", "-q", "-b", "side")
    side = commit(repo, "s")
    git(repo, "checkout", "-q", "-")
    commit(repo, "b")

    with pytest.raises(ValueError, match="not an ancestor of HEAD"):
        resolve_review_range(f"{side}..HEAD", repo=str(repo))


def test_three_dot_range_resolves_the_same_as_two_dot(repo):
    first = commit(repo, "a")
    head = commit(repo, "b")

    resolved = resolve_review_range(f"{first}...HEAD", repo=str(repo))

    assert resolved == {"start": first, "head": head}


@pytest.mark.parametrize("spec", ["abc123", "..HEAD", "abc123.."])
def test_rejects_a_range_that_is_not_start_dots_head(repo, spec):
    commit(repo, "a")

    with pytest.raises(ValueError, match="Expected a range like '<sha>..HEAD'"):
        resolve_review_range(spec, repo=str(repo))


def branch_off(repo, base_branch):
    """Commit once on base_branch, then branch off it with one commit of
    its own; returns the merge-base."""
    base = commit(repo, "base")
    git(repo, "branch", "-M", base_branch)
    git(repo, "checkout", "-q", "-b", "feature")
    commit(repo, "feature")
    return base


def test_the_default_range_prefers_origin_head_then_falls_back_when_it_dangles(repo):
    main_base = commit(repo, "base")
    git(repo, "branch", "-M", "main")
    trunk_base = commit(repo, "trunk")
    git(repo, "update-ref", "refs/remotes/origin/trunk", trunk_base)
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
    git(repo, "reset", "-q", "--hard", main_base)
    git(repo, "checkout", "-q", "-b", "feature", trunk_base)
    commit(repo, "feature")

    # origin/HEAD names the default branch, over a local main.
    assert default_review_range(str(repo)) == f"{trunk_base}..HEAD"

    # Once the branch it points at is gone, main is used instead.
    git(repo, "update-ref", "-d", "refs/remotes/origin/trunk")
    assert default_review_range(str(repo)) == f"{main_base}..HEAD"


@pytest.mark.parametrize(
    "base_ref",
    ["refs/heads/master", "refs/remotes/origin/main", "refs/remotes/origin/master"],
)
def test_the_default_range_falls_back_to_master_and_remote_only_branches(repo, base_ref):
    base = branch_off(repo, "scratch")
    git(repo, "update-ref", base_ref, base)
    git(repo, "branch", "-D", "scratch")

    assert default_review_range(str(repo)) == f"{base}..HEAD"


def test_the_default_range_rejects_a_head_with_no_history_in_common_with_main(repo):
    commit(repo, "base")
    git(repo, "branch", "-M", "main")
    git(repo, "checkout", "-q", "--orphan", "unrelated")
    commit(repo, "unrelated")

    with pytest.raises(ValueError, match="shares no history with main"):
        default_review_range(str(repo))
