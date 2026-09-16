"""The mock's model of a remote must not let tests pass for the wrong reason.

The publisher's retry path is ``delete_tag -> fetch -> reset_keep(FETCH_HEAD)``.
If the mock's FETCH_HEAD does not name the remote tip, or the mock forgets
which commits a push published, a rollback test can end at the right commit
by coincidence rather than because the reset was modelled.
"""

from datetime import datetime, timezone
from pathlib import Path

from auto_version.git.mock_impl import MockGitRepository
from auto_version.models import CommitInfo


def _commit(sha: str) -> CommitInfo:
    return CommitInfo(
        sha=sha,
        short_sha=sha[:7],
        message=f"fix: {sha}",
        commit_type="fix",
        scope=None,
        description=sha,
        body="",
        timestamp=datetime.now(timezone.utc),
        affected_files=[Path("x.py")],
    )


def test_fetch_names_the_remote_tip_even_when_nothing_arrives():
    """FETCH_HEAD is the newest commit the remote has, never a sentinel.

    With no winner registered the remote has not moved, so the fetched tip is
    the pre-release commit and a retry's reset lands there. Left unset, the
    reset would no-op on an absent target, and HEAD would end up at the right
    commit only because local commits happen to be dropped first.
    """
    repo = MockGitRepository()
    repo.add_commit(_commit("base"))
    repo.create_commit("release: 1.0.1", [Path("pyproject.toml")])

    repo.fetch("origin", "main")

    assert repo.resolve("FETCH_HEAD") == "base"
    repo.reset_keep("FETCH_HEAD")
    assert repo.resolve("HEAD") == "base"


def test_a_successful_push_publishes_the_local_commits():
    """Once pushed, a release commit is remote history and survives resets.

    A repo reused for a second release that then loses a race would otherwise
    see its first, published release discarded by the retry's reset as though
    it were still local-only.
    """
    repo = MockGitRepository()
    repo.add_commit(_commit("base"))
    first = repo.create_commit("release: 1.0.1", [Path("pyproject.toml")])
    repo.push("origin", ["HEAD:refs/heads/main", "refs/tags/kg-1.0.1"])
    repo.create_commit("release: 1.0.2", [Path("pyproject.toml")])

    repo.reset_keep(first)

    assert repo.resolve("HEAD") == first
