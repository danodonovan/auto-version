"""Abstract interface for git operations."""

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from auto_version.models import CommitInfo


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
    def get_current_branch(self) -> str:
        """Get the name of the current branch."""
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
