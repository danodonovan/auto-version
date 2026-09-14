"""Abstract interface for git operations."""

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from auto_version.models import CommitInfo


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
        """Create a commit with the specified files.

        Args:
            message: Commit message
            files: List of file paths to stage and commit

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
        called "HEAD". Callers must handle None explicitly.
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
    def fetch(self, remote: str, branch: str) -> None:
        """Fetch a branch from a remote, updating its remote-tracking ref.

        Args:
            remote: Remote name (e.g. "origin")
            branch: Branch to fetch (e.g. "main")
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
    def reset_hard(self, ref: str) -> None:
        """Discard local commits and working-tree changes, moving to ``ref``.

        Args:
            ref: Reference to reset onto (e.g. "origin/main")
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
    def is_dirty(self) -> bool:
        """Whether tracked files have staged or unstaged modifications.

        Untracked files do not count: ``git reset --hard`` leaves them alone,
        so treating them as dirty would reject a checkout that is in fact
        safe to reset.
        """
        pass
