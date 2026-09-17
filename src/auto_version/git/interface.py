"""Abstract interface for git operations."""

import re
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from auto_version.models import CommitInfo

_CREDENTIAL_URL = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]*://)[^/\s@]+@")


def scrub_credentials(text: str) -> str:
    """Replace userinfo in every URL within ``text`` with ``***``.

    Works on arbitrary text, not just a bare remote, because credentials can
    arrive in captured git output as well as in arguments we assembled
    ourselves. scp-style remotes (``git@host:path``) are left alone: they
    carry no secret, and rewriting them would make suggested commands wrong.
    """
    return _CREDENTIAL_URL.sub(r"\1***@", text)


def redact_remote(remote: str) -> str:
    """Hide any credentials embedded in a remote before displaying it.

    A remote may be a URL rather than a name, and a URL may carry userinfo
    (``https://token@host/repo.git``). Those strings end up in error messages
    and in the commands this tool suggests, both of which reach CI logs, so
    the credential is stripped for display while callers keep the original
    for git itself.
    """
    return scrub_credentials(remote)


class PushRejected(Exception):
    """A push to the remote was rejected.

    ``non_fast_forward`` distinguishes the one failure worth retrying — the
    remote branch moved under us, so re-deriving the release against the new
    tip will succeed — from failures that retrying can only repeat (bad
    credentials, no such remote, network down).
    """

    def __init__(self, message: str, *, non_fast_forward: bool) -> None:
        super().__init__(message)
        self.non_fast_forward = non_fast_forward


class BranchDiverged(PushRejected):
    """The remote moved, and the branch carries commits it does not contain.

    Distinct from a plain rejection because the advice differs: a plain
    rejection is worth re-running, whereas this one will recur until the
    branch is rebased, so its message is self-contained.
    """


class GitRepository(ABC):
    """Abstract interface for git repository operations."""

    @abstractmethod
    def get_tags(self, pattern: str | None = None) -> list[str]:
        """Get all tags, optionally filtered by pattern.

        Args:
            pattern: Optional glob pattern to filter tags (e.g., "mypackage-*")

        Returns:
            List of tag names sorted by version (newest first)
        """
        pass

    @abstractmethod
    def get_commits_since(
        self, since_ref: str | None, path_filters: list[str] | None = None
    ) -> list[CommitInfo]:
        """Get commits since a reference, optionally filtered by paths.

        Args:
            since_ref: Git reference (tag, sha, etc.) to start from. If None, get all commits.
            path_filters: Optional list of path patterns to filter commits by

        Returns:
            List of commits from oldest to newest
        """
        pass

    @abstractmethod
    def get_changed_files(self, commit_sha: str) -> list[Path]:
        """Get list of files changed in a commit.

        Args:
            commit_sha: Commit SHA to examine

        Returns:
            List of file paths changed in the commit
        """
        pass

    @abstractmethod
    def create_tag(self, name: str, message: str, commit: str = "HEAD") -> None:
        """Create an annotated tag.

        Args:
            name: Tag name
            message: Tag message
            commit: Commit to tag (default: HEAD)
        """
        pass

    @abstractmethod
    def create_commit(self, message: str, files: list[Path]) -> str:
        """Create a commit containing HEAD's tree with ``files`` applied.

        ``files`` is exhaustive, not advisory: the commit's diff against its
        parent must cover exactly these paths. Anything else already staged in
        the worktree stays staged and uncommitted. A release commit is supposed
        to read as "version bump + changelog (+ lock file)", and unrelated work
        published under a ``release:`` message is work nobody will find again.

        Args:
            message: Commit message
            files: The only paths this commit may change

        Returns:
            SHA of the created commit
        """
        pass

    @abstractmethod
    def get_current_branch(self) -> str | None:
        """Get the name of the current branch, or None if HEAD is detached.

        Returns None rather than a sentinel string: a detached HEAD has no
        branch, and a placeholder that looks like a branch name will be used
        like one — ``HEAD:refs/heads/HEAD`` pushes a remote branch literally
        called "HEAD". Callers must handle None explicitly. An unborn HEAD is
        not detached: it names the branch its first commit will land on, and
        that name is returned.
        """
        pass

    @abstractmethod
    def get_repo_root(self) -> Path:
        """Get the root directory of the git repository."""
        pass

    @abstractmethod
    def stage_files(self, files: list[Path]) -> None:
        """Stage files for commit.

        Args:
            files: List of file paths to stage
        """
        pass

    @abstractmethod
    def fetch(self, remote: str, branch: str) -> str:
        """Fetch a branch from a remote and return a ref naming its tip.

        Callers must reset to the returned ref rather than composing
        ``<remote>/<branch>`` themselves: the remote-tracking ref is only
        updated opportunistically and can be left stale, or not exist at all
        when the remote is given as a URL.

        Args:
            remote: Remote name or URL
            branch: Branch to fetch (e.g. "main")

        Returns:
            A ref that resolves to the fetched tip.
        """
        pass

    @abstractmethod
    def push(self, remote: str, refspecs: list[str]) -> None:
        """Push refspecs to a remote as a single all-or-nothing update.

        Args:
            remote: Remote name (e.g. "origin")
            refspecs: Refspecs to push, e.g.
                ``["HEAD:refs/heads/main", "refs/tags/pkg-1.2.3"]``

        Raises:
            PushRejected: The remote refused the update. Check
                ``non_fast_forward`` to decide whether a retry can help.
        """
        pass

    @abstractmethod
    def reset_keep(self, ref: str) -> None:
        """Move HEAD to ``ref``, refusing to overwrite local changes.

        ``git reset --keep`` semantics: files that differ between HEAD and
        ``ref`` are updated; if any of those has local modifications the
        reset aborts and changes nothing. On a clean worktree this is exactly
        a hard reset. On a dirty one it is the difference between undoing this
        tool's own commit and destroying a file the user, or a build command,
        edited — so it is the only reset this tool performs.

        Args:
            ref: Reference to reset onto (e.g. "FETCH_HEAD", a SHA)

        Raises:
            An implementation-defined error if a modified file would be
            overwritten. The worktree is unchanged in that case.
        """
        pass

    @abstractmethod
    def delete_tag(self, name: str) -> None:
        """Delete a tag from the local repository only.

        A tag that is already absent is not an error. Any other failure must
        raise: callers delete a tag precisely so a following reset cannot
        orphan it, so a swallowed failure defeats the point.

        Args:
            name: Tag name to delete
        """
        pass

    @abstractmethod
    def resolve(self, ref: str) -> str:
        """Resolve a ref to its commit SHA.

        Args:
            ref: Any revision git understands ("HEAD", "FETCH_HEAD", a SHA)

        Returns:
            The full commit SHA.
        """
        pass

    @abstractmethod
    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """Whether ``ancestor`` is reachable from ``descendant``.

        Used to decide whether resetting onto a fetched tip would discard
        local work: if the pre-release commit is reachable from that tip, the
        reset can only drop what this tool created.

        Args:
            ancestor: Commit expected to be contained in ``descendant``
            descendant: Commit to search from
        """
        pass

    @abstractmethod
    def is_dirty(self) -> bool:
        """Whether the worktree holds local state that a reset would destroy.

        Untracked files count. ``git reset --keep`` refuses to overwrite an
        untracked file whose path the target tree adds, so a retry landing on
        such a tip would abort midway rather than complete. Ignored files do
        not count.
        """
        pass
