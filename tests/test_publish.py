"""Tests for release publication and its behaviour when a push races.

All tests use MockGitRepository (never real git). The mock is programmed with
``queue_push_failures()`` to simulate losing a race to a concurrent release
job, and with ``add_tag_arriving_on_fetch()`` to make the winner's tag appear
when we re-sync — so the recomputed version is derived from the new tip, just
as it would be against a real remote.

``sleep`` is injected throughout so the backoff does not slow the suite.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from auto_version.config import Config
from auto_version.git.interface import PushRejected
from auto_version.git.mock_impl import MockGitRepository
from auto_version.models import CommitInfo, VersionBump
from auto_version.orchestration.release import ReleaseOrchestrator


def _config(tmp_path: Path) -> Config:
    return Config(
        tag_format="kg-{version}",
        version_toml=["pyproject.toml:project.version"],
        path_filters=["."],
        package_root=tmp_path,
    )


def _commit(sha: str, message: str = "fix: a fix") -> CommitInfo:
    return CommitInfo(
        sha=sha,
        short_sha=sha[:7],
        message=message,
        commit_type="fix",
        scope=None,
        description=message.split(": ", 1)[-1],
        body="",
        timestamp=datetime.now(timezone.utc),
        affected_files=[Path("kg/thing.py")],
    )


@pytest.fixture
def package(tmp_path: Path) -> Path:
    """A minimal package tree that release() can write version files into."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "kg"\nversion = "1.0.0"\n'
    )
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n")
    return tmp_path


@pytest.fixture
def repo(package: Path) -> MockGitRepository:
    """A repo tagged kg-1.0.0 with one releasable commit after it."""
    repo = MockGitRepository(repo_root=package)
    repo.add_commit(_commit("base", "chore: base"))
    repo.add_tag("kg-1.0.0", "base")
    repo.add_commit(_commit("fix1"))
    return repo


def _publish(repo: MockGitRepository, package: Path, **kwargs):
    orchestrator = ReleaseOrchestrator(repo, _config(package))
    kwargs.setdefault("sleep", lambda _: None)
    return orchestrator.release_and_publish(**kwargs)


# --- the happy path ---


def test_pushes_commit_and_tag_atomically(repo, package):
    """One push carrying both refs, so the tag cannot land without the commit."""
    result = _publish(repo, package)

    assert str(result.new_version) == "1.0.1"
    pushes = [op for op in repo.get_operations() if op.startswith("push:")]
    assert pushes == ["push: origin HEAD:refs/heads/main refs/tags/kg-1.0.1"]


def test_no_push_when_nothing_to_release(package):
    """A NONE bump must not touch the remote at all."""
    repo = MockGitRepository(repo_root=package)
    repo.add_commit(_commit("base", "chore: base"))
    repo.add_tag("kg-1.0.0", "base")

    result = _publish(repo, package)

    assert result.bump_type == VersionBump.NONE
    assert not [op for op in repo.get_operations() if op.startswith("push:")]


def test_pushes_to_named_remote_and_branch(repo, package):
    """--remote/--branch are honoured rather than assumed."""
    _publish(repo, package, remote="upstream", branch="release")

    assert (
        "push: upstream HEAD:refs/heads/release refs/tags/kg-1.0.1"
        in repo.get_operations()
    )


# --- losing the race ---


def test_recomputes_version_after_rejected_push(repo, package):
    """The losing job re-derives its version against the winner's tag.

    This is the case that breaks today: both jobs compute 1.0.1, one lands,
    and the other must become 1.0.2 rather than replaying a stale 1.0.1.
    """
    repo.queue_push_failures(1)
    repo.add_tag_arriving_on_fetch("kg-1.0.1", "winner")

    result = _publish(repo, package)

    assert str(result.new_version) == "1.0.2"
    pushes = [op for op in repo.get_operations() if op.startswith("push:")]
    assert pushes == [
        "push: origin HEAD:refs/heads/main refs/tags/kg-1.0.1",
        "push: origin HEAD:refs/heads/main refs/tags/kg-1.0.2",
    ]


def test_discards_stale_tag_before_resetting(repo, package):
    """The stale tag is deleted *before* the reset that orphans its commit.

    Ordering is the point: a tag left pointing at a discarded commit would be
    published as a non-ancestor of the branch, corrupting the tag history the
    version calculation reads.
    """
    repo.queue_push_failures(1)
    repo.add_tag_arriving_on_fetch("kg-1.0.1", "winner")

    _publish(repo, package)

    ops = repo.get_operations()
    assert ops.index("delete_tag: kg-1.0.1") < ops.index("reset_hard: origin/main")
    assert ops.index("reset_hard: origin/main") > ops.index("fetch: origin main")


def test_survives_several_consecutive_losses(repo, package):
    """Retrying continues while attempts remain."""
    repo.queue_push_failures(2)
    repo.add_tag_arriving_on_fetch("kg-1.0.1", "winner")

    result = _publish(repo, package, retries=3)

    assert str(result.new_version) == "1.0.2"
    assert len([op for op in repo.get_operations() if op.startswith("push:")]) == 3


# --- giving up, loudly ---


def test_raises_when_retries_exhausted(repo, package):
    """Exhaustion must raise, never return quietly.

    The shell loop this replaces exited 0 on exhaustion, turning a loud
    failure into a silent no-op release.
    """
    repo.queue_push_failures(5)

    with pytest.raises(PushRejected):
        _publish(repo, package, retries=2)

    assert len([op for op in repo.get_operations() if op.startswith("push:")]) == 3


def test_retries_disabled_by_zero(repo, package):
    """retries=0 means a single attempt."""
    repo.queue_push_failures(1)

    with pytest.raises(PushRejected):
        _publish(repo, package, retries=0)

    assert len([op for op in repo.get_operations() if op.startswith("push:")]) == 1


def test_does_not_retry_unrelated_failures(repo, package):
    """Bad credentials or a missing remote must fail immediately.

    Retrying cannot fix them, and doing so three times would obscure the
    cause and hammer the remote.
    """
    repo.queue_push_failures(3, non_fast_forward=False)

    with pytest.raises(PushRejected) as excinfo:
        _publish(repo, package, retries=3)

    assert excinfo.value.non_fast_forward is False
    ops = repo.get_operations()
    assert len([op for op in ops if op.startswith("push:")]) == 1
    assert not [op for op in ops if op.startswith("fetch:")]


# --- backoff ---


def test_backoff_is_bounded_and_jittered():
    """Jitter keeps racing jobs from retrying in lockstep; the cap bounds it."""
    delays = [ReleaseOrchestrator._backoff(attempt) for attempt in range(6)]

    assert all(0.0 <= d <= 8.0 for d in delays)
    assert ReleaseOrchestrator._backoff(10) <= 8.0
