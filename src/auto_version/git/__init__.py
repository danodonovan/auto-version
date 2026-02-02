"""Git operations abstraction."""

from auto_version.git.interface import GitRepository
from auto_version.git.mock_impl import MockGitRepository
from auto_version.git.pygit2_impl import PyGit2Repository

__all__ = ["GitRepository", "MockGitRepository", "PyGit2Repository"]
