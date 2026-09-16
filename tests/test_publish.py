"""Tests for release publication and its behaviour when a push races.

All tests use MockGitRepository (never real git). The mock is programmed with
``queue_push_failures()`` to simulate losing a race to a concurrent release
job, and with ``add_release_arriving_on_fetch()`` to make the winner's commit
*and* tag appear when we re-sync. Both halves matter: a tag whose commit is
missing cannot be resolved, so the mock would treat all history as unreleased
and a recomputed version would look plausible for the wrong reason.

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


def _release_commit(sha: str, package: str) -> CommitInfo:
    """A `release:` commit for `package`, as the winning job would push."""
    return CommitInfo(
        sha=sha,
        short_sha=sha[:7],
        message=f"release: {package} 1.0.1 [skip ci]",
        commit_type="release",
        scope=None,
        description=f"{package} 1.0.1",
        body="",
        timestamp=datetime.now(timezone.utc),
        affected_files=[Path(f"{package}/pyproject.toml")],
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


def test_recomputes_against_the_winning_release(repo, package):
    """The loser re-derives its version from history that now contains the winner.

    The winner's release commit *and* its tag must both arrive. Modelling only
    the tag makes `get_commits_since` unable to resolve it, so the mock treats
    all history as unreleased and any recomputed version looks plausible — the
    test would then pass for a reason the real code never exercises.

    Here kg-1.0.1 is taken by the winner and a further kg commit landed after
    it, so the honest answer is 1.0.2.
    """
    repo.queue_push_failures(1)
    repo.add_release_arriving_on_fetch(_release_commit("winner", "kg"), "kg-1.0.1")
    repo.add_release_arriving_on_fetch(_commit("fix2", "fix: landed after"))

    result = _publish(repo, package)

    assert str(result.new_version) == "1.0.2"
    pushes = [op for op in repo.get_operations() if op.startswith("push:")]
    assert pushes == [
        "push: origin HEAD:refs/heads/main refs/tags/kg-1.0.1",
        "push: origin HEAD:refs/heads/main refs/tags/kg-1.0.2",
    ]


def test_reports_nothing_to_do_when_the_winner_released_our_commits(repo, package):
    """Losing to the *same* package is not an error — the work is already out.

    The winner's release covered exactly the commits we were releasing, so
    after resyncing there is nothing left. NONE is the correct answer, and no
    second push should be attempted.
    """
    repo.queue_push_failures(1)
    repo.add_release_arriving_on_fetch(_release_commit("winner", "kg"), "kg-1.0.1")

    result = _publish(repo, package)

    assert result.bump_type == VersionBump.NONE
    pushes = [op for op in repo.get_operations() if op.startswith("push:")]
    assert pushes == ["push: origin HEAD:refs/heads/main refs/tags/kg-1.0.1"]


def test_recomputes_when_another_package_wins_the_race(repo, package):
    """The healnet case: two packages releasing from one merge.

    The winner's tag is in a different namespace, so our own version is
    unaffected - we simply retry onto the new tip and publish 1.0.1.
    """
    repo.queue_push_failures(1)
    repo.add_release_arriving_on_fetch(_release_commit("winner", "dwpc"), "dwpc-1.0.1")

    result = _publish(repo, package)

    assert str(result.new_version) == "1.0.1"
    assert len([op for op in repo.get_operations() if op.startswith("push:")]) == 2


def test_discards_stale_tag_before_resetting(repo, package):
    """The stale tag is deleted *before* the reset that orphans its commit.

    Ordering is the point: a tag left pointing at a discarded commit would be
    published as a non-ancestor of the branch, corrupting the tag history the
    version calculation reads.
    """
    repo.queue_push_failures(1)
    repo.add_release_arriving_on_fetch(_release_commit("winner", "dwpc"), "dwpc-1.0.1")

    _publish(repo, package)

    ops = repo.get_operations()
    assert ops.index("delete_tag: kg-1.0.1") < ops.index("reset_keep: FETCH_HEAD")
    assert ops.index("reset_keep: FETCH_HEAD") > ops.index("fetch: origin main")


def test_survives_several_consecutive_losses(repo, package):
    """Retrying continues while attempts remain.

    The winner is another package, so our version is unchanged by the race —
    what this asserts is that losing twice still ends in a published release
    rather than exhausting.
    """
    repo.queue_push_failures(2)
    repo.add_release_arriving_on_fetch(_release_commit("winner", "dwpc"), "dwpc-1.0.1")

    result = _publish(repo, package, retries=3)

    assert str(result.new_version) == "1.0.1"
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

    ops = repo.get_operations()
    assert len([op for op in ops if op.startswith("push:")]) == 1
    assert not [op for op in ops if op.startswith("fetch:")]


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


# --- guards: refuse rather than do damage ---


def test_refuses_a_dirty_worktree(repo, package):
    """A retry resets the checkout, so local state must block first.

    The check has to precede the first release() call, because release()
    dirties the tree itself by writing version files and the changelog.
    Untracked files count too: a reset spares them only while their path is
    absent from the tree being reset onto.
    """
    repo.set_dirty(True)

    with pytest.raises(ValueError, match="local modifications"):
        _publish(repo, package)

    assert not [op for op in repo.get_operations() if op.startswith("push:")]
    assert not [op for op in repo.get_operations() if op.startswith("create_commit:")]


def test_refuses_a_detached_head_without_an_explicit_branch(repo, package):
    """A detached HEAD has no branch; guessing one could publish anywhere.

    Before, get_current_branch() returned the sentinel "HEAD", which flowed
    into the refspec as HEAD:refs/heads/HEAD and would have created a remote
    branch literally named "HEAD" — a normal state for a CI tag build.
    """
    repo.set_current_branch(None)

    with pytest.raises(ValueError, match="detached"):
        _publish(repo, package)

    assert not [op for op in repo.get_operations() if op.startswith("push:")]


def test_detached_head_is_fine_with_an_explicit_branch(repo, package):
    """--branch says where the release lands, so detachment stops mattering."""
    repo.set_current_branch(None)

    result = _publish(repo, package, branch="main")

    assert str(result.new_version) == "1.0.1"
    assert (
        "push: origin HEAD:refs/heads/main refs/tags/kg-1.0.1" in repo.get_operations()
    )


def test_rejects_negative_retries(repo, package):
    """Negative retries emptied the loop and hit an internal assertion."""
    with pytest.raises(ValueError, match="zero or greater"):
        _publish(repo, package, retries=-1)


def test_only_unborn_head_errors_fall_back_to_plain_release(package):
    """Only the specific unborn-HEAD git error should enter the fallback."""
    import subprocess

    repo = MockGitRepository(repo_root=package)

    def unborn_head(ref: str) -> str:
        if ref == "HEAD":
            raise subprocess.CalledProcessError(
                128,
                ["git", "rev-parse", "HEAD"],
                stderr=(
                    "fatal: ambiguous argument 'HEAD': "
                    "unknown revision or path not in the working tree."
                ),
            )
        return ref

    repo.resolve = unborn_head  # type: ignore[method-assign]

    result = _publish(repo, package)

    assert result.bump_type == VersionBump.NONE


def test_non_unborn_head_resolution_failures_propagate(package):
    """Unexpected HEAD resolution failures must not be treated as unborn."""
    repo = MockGitRepository(repo_root=package)

    def unexpected_failure(ref: str) -> str:
        if ref == "HEAD":
            raise RuntimeError("resolve failed unexpectedly")
        return ref

    repo.resolve = unexpected_failure  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="resolve failed unexpectedly"):
        _publish(repo, package)


# --- what is left on disk after a failure ---


def test_discards_the_release_when_every_attempt_is_rejected(repo, package):
    """Exhaustion must clean up, or the stray tag silences the next run.

    Any local release tag makes release() report NONE, so leaving one behind
    after a lost race would make the advertised "re-run" a silent no-op.
    """
    repo.queue_push_failures(5)

    with pytest.raises(PushRejected):
        _publish(repo, package, retries=1)

    ops = repo.get_operations()
    assert "delete_tag: kg-1.0.1" in ops
    assert "reset_keep: FETCH_HEAD" in ops
    # the tag is gone, so a re-run recomputes rather than reporting NONE
    assert "kg-1.0.1" not in repo.get_tags()


def test_keeps_the_release_when_the_failure_is_not_contention(repo, package):
    """A correct release whose push failed externally is left to push by hand.

    Discarding it would throw away valid work for a cause that has nothing to
    do with the release - bad credentials, a hook, an unknown remote.
    """
    repo.queue_push_failures(1, non_fast_forward=False)

    with pytest.raises(PushRejected):
        _publish(repo, package, retries=3)

    ops = repo.get_operations()
    assert "kg-1.0.1" in repo.get_tags()
    assert not [op for op in ops if op.startswith("delete_tag:")]
    assert not [op for op in ops if op.startswith("reset_keep:")]


def test_does_not_reset_when_tag_deletion_fails(repo, package):
    """A failed deletion must abort, not proceed to orphan the tag.

    Deleting before the reset is the whole invariant; resetting anyway would
    strand the tag on a discarded commit and publish a non-ancestor tag.
    """
    repo.queue_push_failures(1)
    repo.fail_tag_delete("kg-1.0.1")

    with pytest.raises(RuntimeError, match="cannot delete tag"):
        _publish(repo, package)

    assert not [op for op in repo.get_operations() if op.startswith("reset_keep:")]


def test_rolls_back_rather_than_resetting_away_local_commits(repo, package):
    """A reset may only land on a tip containing where publishing started.

    `is_dirty` catches uncommitted work, but a branch can be perfectly clean
    and still carry commits the remote has never seen. Resetting onto the
    fetched tip would delete those along with the release, so publishing
    rolls back to its own starting point and asks for a rebase instead.
    """
    repo.queue_push_failures(1)
    repo.add_release_arriving_on_fetch(_release_commit("winner", "dwpc"), "dwpc-1.0.1")
    repo.set_diverged_from_remote(True)

    with pytest.raises(PushRejected, match="commits that are not on it"):
        _publish(repo, package)

    ops = repo.get_operations()
    # rolled back to the pre-release commit, not to the fetched tip
    assert "reset_keep: fix1" in ops
    assert "reset_keep: FETCH_HEAD" not in ops
    # and the rollback actually restored it, not merely logged the intent
    assert repo.resolve("HEAD") == "fix1"
    # and the release it created was cleaned up
    assert "delete_tag: kg-1.0.1" in ops
    assert "kg-1.0.1" not in repo.get_tags()
    # only ever one push attempt: retrying cannot help here
    assert len([op for op in ops if op.startswith("push:")]) == 1


def test_divergence_advice_says_when_the_remote_was_redacted(repo, package):
    """The rebase command prints a redacted URL, so it is not runnable as shown.

    The non-retryable push path already says so; the divergence path is the
    only other place a command naming the remote is printed.
    """
    repo.queue_push_failures(1)
    repo.add_release_arriving_on_fetch(_release_commit("winner", "dwpc"), "dwpc-1.0.1")
    repo.set_diverged_from_remote(True)

    with pytest.raises(PushRejected) as excinfo:
        _publish(repo, package, remote="https://ghp_secret@example.com/r.git")

    message = str(excinfo.value)
    assert "ghp_secret" not in message
    assert "git fetch https://***@example.com/r.git main" in message
    assert "redacted" in message


def test_divergence_advice_is_plain_for_a_named_remote(repo, package):
    """No redaction happened, so no caveat about it."""
    repo.queue_push_failures(1)
    repo.add_release_arriving_on_fetch(_release_commit("winner", "dwpc"), "dwpc-1.0.1")
    repo.set_diverged_from_remote(True)

    with pytest.raises(PushRejected) as excinfo:
        _publish(repo, package)

    assert "git fetch origin main" in str(excinfo.value)
    assert "redacted" not in str(excinfo.value)


def test_checks_containment_against_the_fetched_tip(repo, package):
    """The containment test uses FETCH_HEAD, not a composed remote ref.

    `git fetch <remote> <branch>` updates the remote-tracking ref only
    opportunistically, so comparing against "<remote>/<branch>" can consult a
    stale ref — or one that does not exist when the remote is a URL.
    """
    repo.queue_push_failures(1)
    repo.add_release_arriving_on_fetch(_release_commit("winner", "dwpc"), "dwpc-1.0.1")

    _publish(repo, package)

    checks = [op for op in repo.get_operations() if op.startswith("is_ancestor:")]
    assert checks == ["is_ancestor: fix1 in FETCH_HEAD"]


def test_rolls_back_if_the_resync_fetch_fails(repo, package):
    """A failed resync must not strand an untagged release commit.

    The tag is deleted before the fetch, so bailing out there would leave the
    version bump and changelog committed at HEAD with nothing marking them as
    released. A later run cannot tell that from unreleased work and releases
    on top of it, duplicating the commit and its changelog entry.
    """
    repo.queue_push_failures(1)
    repo.fail_next_fetch()

    with pytest.raises(RuntimeError, match="fetch failed"):
        _publish(repo, package)

    ops = repo.get_operations()
    assert "delete_tag: kg-1.0.1" in ops
    assert "reset_keep: fix1" in ops  # back to the pre-release commit
    assert "kg-1.0.1" not in repo.get_tags()


def test_rolls_back_if_the_containment_check_fails(repo, package):
    """`is_ancestor` propagates fatal merge-base errors, after the tag is gone.

    Like a failed resync fetch, an exception here must not strand an untagged
    release commit at HEAD for the next run to release on top of.
    """
    repo.queue_push_failures(1)

    def broken_is_ancestor(ancestor: str, descendant: str) -> bool:
        raise RuntimeError("git merge-base --is-ancestor failed (exit 128)")

    repo.is_ancestor = broken_is_ancestor  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="merge-base"):
        _publish(repo, package)

    ops = repo.get_operations()
    assert "delete_tag: kg-1.0.1" in ops
    assert "reset_keep: fix1" in ops  # back to the pre-release commit
    assert repo.resolve("HEAD") == "fix1"
    assert "kg-1.0.1" not in repo.get_tags()


def test_advances_the_baseline_after_each_successful_retry(repo, package):
    """The containment check must compare against *this* attempt's start.

    Left at the original pre-release HEAD, attempt 2 would happily accept a
    fetched tip that dropped what attempt 1 already reset onto — the
    rewritten-history case the check exists to catch — and the fetch-error
    rollback would rewind further than this attempt began.
    """
    repo.queue_push_failures(2)
    repo.add_release_arriving_on_fetch(_release_commit("winner1", "dwpc"), "dwpc-1.0.1")

    _publish(repo, package, retries=3)

    checks = [op for op in repo.get_operations() if op.startswith("is_ancestor:")]
    # first attempt compares against the pre-release HEAD, the second against
    # the tip the first attempt landed on — not the original again
    assert checks[0] == "is_ancestor: fix1 in FETCH_HEAD"
    assert checks[1] != checks[0]
    assert checks[1] == "is_ancestor: winner1 in FETCH_HEAD"


def test_rolls_back_with_keep_when_the_build_command_leaves_files_behind(repo, package):
    """A build command can dirty the worktree after the pre-flight check.

    The release is undone with `reset --keep`, which refuses to touch any file
    with local changes, so the leak survives and the release commit and tag
    are gone — leaving a re-run free to recompute once the leak is dealt with.
    Nothing is fetched: the check runs before `delete_tag`/`fetch`.
    """
    repo.queue_push_failures(1)
    repo.add_release_arriving_on_fetch(_release_commit("winner", "dwpc"), "dwpc-1.0.1")

    orchestrator = ReleaseOrchestrator(repo, _config(package))
    original_release = orchestrator.release

    def release_then_dirty(*args, **kwargs):
        result = original_release(*args, **kwargs)
        repo.set_dirty(True)  # the build command's leftovers
        return result

    orchestrator.release = release_then_dirty  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="rolled back to fix1"):
        orchestrator.release_and_publish(sleep=lambda _: None)

    ops = repo.get_operations()
    assert "reset_keep: fix1" in ops  # undone, to where we began
    assert "delete_tag: kg-1.0.1" in ops
    assert "reset_keep: FETCH_HEAD" not in ops  # never reset onto the new tip
    assert not [op for op in ops if op.startswith("fetch:")]
    assert repo.resolve("HEAD") == "fix1"
    assert "kg-1.0.1" not in repo.get_tags()


def test_dirty_check_precedes_the_fetch_so_leftovers_are_never_reset(repo, package):
    """With leftovers present the fetch is never attempted, let alone rolled back.

    `fail_next_fetch()` is armed but never fires: the post-release dirty check
    runs before `delete_tag`/`fetch`, so no reset of any kind can reach the
    leftovers.
    """
    repo.queue_push_failures(1)
    repo.fail_next_fetch()

    orchestrator = ReleaseOrchestrator(repo, _config(package))
    original_release = orchestrator.release

    def release_then_dirty(*args, **kwargs):
        result = original_release(*args, **kwargs)
        repo.set_dirty(True)
        return result

    orchestrator.release = release_then_dirty  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="build command left changes"):
        orchestrator.release_and_publish(sleep=lambda _: None)

    # the armed fetch failure never fired: the dirty check ran first
    assert not [op for op in repo.get_operations() if op.startswith("fetch:")]


def test_git_failures_do_not_leak_remote_credentials(monkeypatch):
    """A failing git command must not repeat a credential URL to the caller.

    CalledProcessError quotes the whole argument list, and that exception
    reaches the CLI's generic handler, bypassing the redaction applied to
    PushRejected. Redacting centrally in _run_git covers every git call.

    No real repository is created (see CLAUDE.md): subprocess is stubbed, so
    this exercises the wiring rather than git itself.
    """
    import subprocess

    from auto_version.git.pygit2_impl import PyGit2Repository

    repo = PyGit2Repository.__new__(PyGit2Repository)
    monkeypatch.setattr(repo, "get_repo_root", lambda: Path("/nowhere"))

    secret_url = "https://ghp_SECRET@nonexistent.invalid/x.git"

    def explode(*args, **kwargs):
        raise subprocess.CalledProcessError(
            128,
            ["git", "fetch", "--tags", secret_url, "main"],
            output=f"fatal: could not read from {secret_url}\n",
            stderr=f"fatal: could not read from {secret_url}\n",
        )

    monkeypatch.setattr(subprocess, "run", explode)

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        repo._run_git("fetch", "--tags", secret_url, "main")

    message = str(excinfo.value)
    assert "ghp_SECRET" not in message
    assert "***@nonexistent.invalid" in message
    assert "ghp_SECRET" not in (excinfo.value.output or "")
    assert "ghp_SECRET" not in (excinfo.value.stderr or "")


def _dirty_after_release(repo, package):
    """An orchestrator whose release() leaves the worktree dirty afterwards."""
    orchestrator = ReleaseOrchestrator(repo, _config(package))
    original_release = orchestrator.release

    def release_then_dirty(*args, **kwargs):
        result = original_release(*args, **kwargs)
        repo.set_dirty(True)
        return result

    orchestrator.release = release_then_dirty  # type: ignore[method-assign]
    return orchestrator


def test_dirty_rollback_restores_the_tag_if_the_reset_fails(repo, package):
    """A failed reset must not leave an untagged release commit behind.

    The tag is deleted before the reset. If the reset then aborts, the tag is
    recreated on the release commit so the checkout is exactly as it was —
    otherwise the next run would find the release commit untagged, treat it as
    unreleased work, and release again on top of it.
    """
    repo.queue_push_failures(1)
    repo.fail_next_reset()

    with pytest.raises(RuntimeError, match="reset --keep aborted"):
        _dirty_after_release(repo, package).release_and_publish(sleep=lambda _: None)

    ops = repo.get_operations()
    reset_at = ops.index("reset_keep: fix1")
    assert ops.index("delete_tag: kg-1.0.1") < reset_at
    assert any(op.startswith("create_tag: kg-1.0.1 at ") for op in ops[reset_at:])
    assert "kg-1.0.1" in repo.get_tags()  # restored


def test_dirty_rollback_leaves_everything_if_tag_deletion_fails(repo, package):
    """Delete-first means a failed deletion moves nothing.

    Reset-then-delete would leave HEAD at the base with the tag still pointing
    at the discarded commit — an orphan tag that silences the next run.
    """
    repo.queue_push_failures(1)
    repo.fail_tag_delete("kg-1.0.1")

    with pytest.raises(RuntimeError, match="cannot delete tag"):
        _dirty_after_release(repo, package).release_and_publish(sleep=lambda _: None)

    assert not [op for op in repo.get_operations() if op.startswith("reset_keep:")]
    assert "kg-1.0.1" in repo.get_tags()


@pytest.mark.parametrize(
    ("arm", "retries"),
    [
        pytest.param(lambda repo: None, 0, id="retries-exhausted"),
        pytest.param(lambda repo: repo.fail_next_fetch(), 3, id="resync-fetch-failed"),
        pytest.param(
            lambda repo: repo.set_diverged_from_remote(True), 3, id="branch-diverged"
        ),
    ],
)
def test_every_rollback_restores_the_tag_if_the_reset_fails(
    repo, package, arm, retries
):
    """A failed rollback reset must leave the release tagged, on every path.

    Each rollback deletes the tag before resetting. If the reset then aborts,
    the tag is recreated on the release commit so the checkout is exactly as
    it was — otherwise HEAD sits on an untagged release commit, which the
    next run cannot tell from unreleased work and releases on top of. The
    dirty-worktree path always did this; these three paths did not.
    """
    repo.queue_push_failures(1)
    arm(repo)
    repo.fail_next_reset()

    with pytest.raises(RuntimeError, match="reset --keep aborted"):
        _publish(repo, package, retries=retries)

    ops = repo.get_operations()
    reset_at = ops.index("reset_keep: fix1")
    assert ops.index("delete_tag: kg-1.0.1") < reset_at
    assert any(op.startswith("create_tag: kg-1.0.1 at ") for op in ops[reset_at:])
    assert "kg-1.0.1" in repo.get_tags()  # restored


def test_retry_restores_the_tag_if_the_reset_onto_the_fetched_tip_fails(repo, package):
    """The forward reset onto FETCH_HEAD is a reset after a delete_tag too."""
    repo.queue_push_failures(1)
    repo.add_release_arriving_on_fetch(_release_commit("winner", "dwpc"), "dwpc-1.0.1")
    repo.fail_next_reset()

    with pytest.raises(RuntimeError, match="reset --keep aborted"):
        _publish(repo, package)

    ops = repo.get_operations()
    reset_at = ops.index("reset_keep: FETCH_HEAD")
    assert any(op.startswith("create_tag: kg-1.0.1 at ") for op in ops[reset_at:])
    assert "kg-1.0.1" in repo.get_tags()  # restored


def test_an_unborn_head_names_its_branch_rather_than_reporting_detached():
    """A fresh repository is not detached: HEAD names the branch to be born.

    Reporting None there made `--push` refuse a fresh repository with the
    detached-HEAD message instead of reaching the unborn fallback, which
    reports "no release needed". Reading `head` raises on an unborn HEAD, so
    the symbolic target is read directly. No real repository is created: the
    pygit2 handle is stubbed.
    """
    from types import SimpleNamespace

    from auto_version.git.pygit2_impl import PyGit2Repository

    class UnbornRepo:
        head_is_detached = False
        head_is_unborn = True

        def lookup_reference(self, name: str) -> SimpleNamespace:
            assert name == "HEAD"
            return SimpleNamespace(target="refs/heads/main")

        @property
        def head(self) -> None:
            raise AssertionError("head must not be read on an unborn HEAD")

    class DetachedRepo:
        head_is_detached = True
        head_is_unborn = False

    repo = PyGit2Repository.__new__(PyGit2Repository)
    repo._repo = UnbornRepo()  # type: ignore[assignment]
    assert repo.get_current_branch() == "main"

    repo._repo = DetachedRepo()  # type: ignore[assignment]
    assert repo.get_current_branch() is None


def test_git_errors_reading_head_propagate_rather_than_reading_as_detached():
    """A broken repository is not a detached HEAD.

    Swallowing GitError here made `--push` answer a corrupt or unreadable HEAD
    with "pass --branch", which cannot help. Only the explicit detached state
    returns None.
    """
    import pygit2

    from auto_version.git.pygit2_impl import PyGit2Repository

    class BrokenRepo:
        head_is_unborn = False

        @property
        def head_is_detached(self) -> bool:
            raise pygit2.GitError("could not read HEAD")

    repo = PyGit2Repository.__new__(PyGit2Repository)
    repo._repo = BrokenRepo()  # type: ignore[assignment]

    with pytest.raises(pygit2.GitError, match="could not read HEAD"):
        repo.get_current_branch()


def test_is_ancestor_surfaces_git_failures_rather_than_answering_no(monkeypatch):
    """Exit 1 is "no"; any other non-zero is an error and must propagate.

    Treating a fatal (bad ref, damaged repository) as "not an ancestor" would
    reset the release and tell the user to rebase for what is actually a git
    failure. Verified exit codes: 0 yes, 1 no, 128 fatal.
    """
    import subprocess

    from auto_version.git.pygit2_impl import PyGit2Repository

    repo = PyGit2Repository.__new__(PyGit2Repository)
    monkeypatch.setattr(repo, "get_repo_root", lambda: Path("/nowhere"))

    def fake_run(argv, **kwargs):
        code = {"yes": 0, "no": 1, "boom": 128}[argv[-1]]
        return subprocess.CompletedProcess(
            argv, code, stdout="", stderr="fatal: bad object"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert repo.is_ancestor("a", "yes") is True
    assert repo.is_ancestor("a", "no") is False
    with pytest.raises(RuntimeError, match="exit 128"):
        repo.is_ancestor("a", "boom")
