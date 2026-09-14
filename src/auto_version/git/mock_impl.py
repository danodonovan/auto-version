"""Mock git repository implementation for testing."""

from datetime import datetime
from pathlib import Path

from auto_version.git.interface import GitRepository, PushRejected
from auto_version.models import CommitInfo


class MockGitRepository(GitRepository):
    """In-memory mock git repository for testing."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self._repo_root = repo_root or Path("/mock/repo")
        self._tags: dict[str, str] = {}  # tag_name -> commit_sha
        self._commits: list[CommitInfo] = []
        self._staged_files: list[Path] = []
        self._operations: list[str] = []  # Log of operations for assertions
        self._local_commit_shas: list[str] = []  # created via create_commit
        self._queued_push_failures: list[bool] = []  # non_fast_forward flags
        self._tags_arriving_on_fetch: dict[str, str] = {}
        self._current_branch: str | None = "main"
        self._dirty = False
        self._tag_delete_failures: set[str] = set()

    def add_commit(self, commit: CommitInfo) -> None:
        """Add a commit to the mock repository."""
        self._commits.append(commit)

    def add_tag(self, name: str, commit_sha: str) -> None:
        """Add a tag to the mock repository."""
        self._tags[name] = commit_sha

    def get_operations(self) -> list[str]:
        """Get log of operations performed."""
        return self._operations.copy()

    def queue_push_failures(self, count: int, non_fast_forward: bool = True) -> None:
        """Make the next ``count`` pushes raise :class:`PushRejected`.

        Models losing a race to another release job (``non_fast_forward``
        True) or a failure retrying cannot fix, such as bad credentials
        (False).
        """
        self._queued_push_failures.extend([non_fast_forward] * count)

    def add_tag_arriving_on_fetch(self, name: str, commit_sha: str) -> None:
        """Register a tag that appears on the next ``fetch`` call.

        Models the winning job's release tag becoming visible once we
        re-sync, so a recomputed version is derived from the new tip.
        """
        self._tags_arriving_on_fetch[name] = commit_sha

    def get_tags(self, pattern: str | None = None) -> list[str]:
        """Get all tags, optionally filtered by pattern."""
        tags = list(self._tags.keys())
        if pattern:
            # Simple glob matching (just prefix for now)
            prefix = pattern.rstrip("*")
            tags = [t for t in tags if t.startswith(prefix)]
        return sorted(tags, reverse=True)

    def get_commits_since(
        self, since_ref: str | None, path_filters: list[str] | None = None
    ) -> list[CommitInfo]:
        """Get commits since a reference."""
        # Find the starting commit
        start_idx = 0
        if since_ref:
            # Check if it's a tag
            if since_ref in self._tags:
                commit_sha = self._tags[since_ref]
            else:
                commit_sha = since_ref

            # Find commit index
            for i, commit in enumerate(self._commits):
                if commit.sha == commit_sha or commit.short_sha == commit_sha:
                    start_idx = i + 1  # Start after this commit
                    break

        # Get commits after the reference
        commits = self._commits[start_idx:]

        # Filter by paths if specified
        if path_filters:
            filtered = []
            for commit in commits:
                for file_path in commit.affected_files:
                    for pattern in path_filters:
                        if self._matches_pattern(file_path, pattern):
                            filtered.append(commit)
                            break
                    else:
                        continue
                    break
            commits = filtered

        return commits

    def get_changed_files(self, commit_sha: str) -> list[Path]:
        """Get list of files changed in a commit."""
        for commit in self._commits:
            if commit.sha == commit_sha or commit.short_sha == commit_sha:
                return commit.affected_files.copy()
        return []

    def create_tag(self, name: str, message: str, commit: str = "HEAD") -> None:
        """Create an annotated tag."""
        if commit == "HEAD" and self._commits:
            commit_sha = self._commits[-1].sha
        else:
            commit_sha = commit
        self._tags[name] = commit_sha
        self._operations.append(f"create_tag: {name} at {commit_sha}")

    def create_commit(self, message: str, files: list[Path]) -> str:
        """Create a commit with the specified files."""
        sha = f"mock_{len(self._commits)}"
        short_sha = sha[:7]
        commit = CommitInfo(
            sha=sha,
            short_sha=short_sha,
            message=message,
            commit_type="",
            scope=None,
            description=message,
            body="",
            timestamp=datetime.now(),
            affected_files=files.copy(),
        )
        self._commits.append(commit)
        self._local_commit_shas.append(sha)
        self._operations.append(f"create_commit: {message}")
        return sha

    def get_current_branch(self) -> str | None:
        """Get the name of the current branch, or None if detached."""
        return self._current_branch

    def set_current_branch(self, branch: str | None) -> None:
        """Set the reported branch; None models a detached HEAD."""
        self._current_branch = branch

    def set_dirty(self, dirty: bool) -> None:
        """Set whether tracked files report modifications."""
        self._dirty = dirty

    def is_dirty(self) -> bool:
        """Whether tracked files have staged or unstaged modifications."""
        return self._dirty

    def get_repo_root(self) -> Path:
        """Get the root directory of the git repository."""
        return self._repo_root

    def stage_files(self, files: list[Path]) -> None:
        """Stage files for commit."""
        self._staged_files.extend(files)
        self._operations.append(f"stage_files: {[str(f) for f in files]}")

    def fetch(self, remote: str, branch: str) -> None:
        """Fetch a branch, revealing any tags registered to arrive."""
        self._operations.append(f"fetch: {remote} {branch}")
        self._tags.update(self._tags_arriving_on_fetch)
        self._tags_arriving_on_fetch.clear()

    def push(self, remote: str, refspecs: list[str]) -> None:
        """Push refspecs, honouring any queued failures."""
        self._operations.append(f"push: {remote} {' '.join(refspecs)}")
        if self._queued_push_failures:
            non_fast_forward = self._queued_push_failures.pop(0)
            raise PushRejected(
                f"mock push rejected (non_fast_forward={non_fast_forward})",
                non_fast_forward=non_fast_forward,
            )

    def reset_hard(self, ref: str) -> None:
        """Discard locally created commits, as a hard reset would."""
        self._operations.append(f"reset_hard: {ref}")
        local = set(self._local_commit_shas)
        self._commits = [c for c in self._commits if c.sha not in local]
        self._local_commit_shas.clear()
        self._staged_files.clear()

    def delete_tag(self, name: str) -> None:
        """Delete a tag from the mock repository.

        Raises if the tag was registered via ``fail_tag_delete`` — modelling a
        real deletion failure (a lock, a corrupt ref), as distinct from an
        absent tag, which is tolerated.
        """
        self._operations.append(f"delete_tag: {name}")
        if name in self._tag_delete_failures:
            raise RuntimeError(f"mock: cannot delete tag {name}")
        self._tags.pop(name, None)

    def fail_tag_delete(self, name: str) -> None:
        """Make ``delete_tag`` raise for this tag name."""
        self._tag_delete_failures.add(name)

    def _matches_pattern(self, file_path: Path, pattern: str) -> bool:
        """Check if a file path matches a pattern."""
        pattern_path = Path(pattern)
        file_str = str(file_path)
        pattern_str = str(pattern_path)

        # Handle "." as "all files"
        if pattern_str == ".":
            return True

        # Simple prefix matching for now
        if pattern_str.endswith("**"):
            prefix = pattern_str.rstrip("*").rstrip("/")
            return file_str.startswith(prefix)

        # Exact match or starts with pattern
        return file_str.startswith(pattern_str)
