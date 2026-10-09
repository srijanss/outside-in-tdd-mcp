import subprocess

import pytest

from core.review_range import resolve_review_range


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
