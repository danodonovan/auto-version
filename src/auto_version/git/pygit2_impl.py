"""Real git repository implementation using pygit2."""

from datetime import datetime, timezone
from pathlib import Path

import pygit2

from auto_version.git.interface import GitRepository
from auto_version.models import CommitInfo


class PyGit2Repository(GitRepository):
    """Real git repository implementation using pygit2."""

    def __init__(self, repo_path: Path | None = None) -> None:
        """Initialize with a repository path.

        Args:
            repo_path: Path to the git repository. If None, discovers from current directory.
        """
        if repo_path is None:
            repo_path = Path.cwd()

        # Discover the git repository
        discovered = pygit2.discover_repository(str(repo_path))
        if not discovered:
            raise ValueError(f"No git repository found at {repo_path}")

        self._repo = pygit2.Repository(discovered)

    def get_tags(self, pattern: str | None = None) -> list[str]:
        """Get all tags, optionally filtered by pattern."""
        from auto_version.models import Version

        tags = []
        for ref in self._repo.listall_references():
            if ref.startswith("refs/tags/"):
                tag_name = ref.replace("refs/tags/", "")
                if pattern is None or self._matches_pattern(tag_name, pattern):
                    tags.append(tag_name)

        # Sort by semantic version (newest first)
        # Extract version from tag name and use for sorting
        def extract_version(tag: str) -> tuple[int, int, int]:
            """Extract version numbers for sorting."""
            try:
                # Try to find version pattern like x.y.z in the tag
                import re

                match = re.search(r"(\d+)\.(\d+)\.(\d+)", tag)
                if match:
                    return (
                        int(match.group(1)),
                        int(match.group(2)),
                        int(match.group(3)),
                    )
            except (ValueError, AttributeError):
                pass
            # Fallback to (0, 0, 0) for non-semver tags
            return (0, 0, 0)

        return sorted(tags, key=extract_version, reverse=True)

    def get_commits_since(
        self, since_ref: str | None, path_filters: list[str] | None = None
    ) -> list[CommitInfo]:
        """Get commits since a reference."""
        # Get the HEAD commit
        try:
            head = self._repo.revparse_single("HEAD")
        except KeyError:
            return []  # Empty repository

        # Set up walker
        walker = self._repo.walk(head.id, pygit2.GIT_SORT_TOPOLOGICAL)

        # If we have a since_ref, hide commits before it
        if since_ref:
            try:
                since_obj = self._repo.revparse_single(since_ref)
                walker.hide(since_obj.id)
            except KeyError:
                raise ValueError(f"Reference not found: {since_ref}")

        # Walk commits and collect those matching filters
        commits = []
        for commit in walker:
            # Get changed files for this commit
            if commit.parents:
                # Get diff from first parent
                diff = self._repo.diff(commit.parents[0], commit)
                changed_files = [Path(delta.new_file.path) for delta in diff.deltas]
            else:
                # First commit - all files are new
                changed_files = []
                for entry in commit.tree:
                    changed_files.append(Path(entry.name))

            # Apply path filters
            if path_filters:
                matches_filter = any(
                    self._file_matches_filters(f, path_filters) for f in changed_files
                )
                if not matches_filter:
                    continue

            # Parse commit message
            message = commit.message.strip()
            commits.append(
                CommitInfo(
                    sha=str(commit.id),
                    short_sha=str(commit.id)[:7],
                    message=message,
                    commit_type="",  # Will be parsed later
                    scope=None,
                    description=message.split("\n")[0],
                    body="\n".join(message.split("\n")[1:]).strip(),
                    timestamp=datetime.fromtimestamp(
                        commit.commit_time, tz=timezone.utc
                    ),
                    affected_files=changed_files,
                )
            )

        # Return in chronological order (oldest first)
        return list(reversed(commits))

    def get_changed_files(self, commit_sha: str) -> list[Path]:
        """Get list of files changed in a commit."""
        try:
            commit = self._repo.revparse_single(commit_sha)
        except KeyError:
            return []

        if not commit.parents:
            return []

        diff = self._repo.diff(commit.parents[0], commit)
        return [Path(delta.new_file.path) for delta in diff.deltas]

    def create_tag(self, name: str, message: str, commit: str = "HEAD") -> None:
        """Create an annotated tag."""
        target = self._repo.revparse_single(commit)

        # Get tagger signature
        signature = self._repo.default_signature

        self._repo.create_tag(
            name,
            target.id,
            pygit2.GIT_OBJECT_COMMIT,
            signature,
            message,
        )

    def create_commit(self, message: str, files: list[Path]) -> str:
        """Create a commit with the specified files."""
        # Files should already be staged via stage_files()
        # Get tree from index
        tree = self._repo.index.write_tree()

        # Get parent commit
        try:
            parent = self._repo.revparse_single("HEAD")
            parents = [parent.id]
        except KeyError:
            parents = []

        # Get signature
        signature = self._repo.default_signature

        # Create commit
        commit_oid = self._repo.create_commit(
            "HEAD",
            signature,
            signature,
            message,
            tree,
            parents,
        )

        return str(commit_oid)

    def get_current_branch(self) -> str:
        """Get the name of the current branch, or "HEAD" if detached.

        Uses ``head_is_detached`` rather than comparing ``head.type`` against
        ``pygit2.GIT_REF_SYMBOLIC``: that module-level constant was moved into
        ``pygit2.enums`` and raises ``AttributeError`` on current pygit2, and
        the old comparison was inverted besides — it returned the branch name
        only when HEAD was symbolic-*resolved*, so a normal checkout reported
        "HEAD". Nothing called this, so it went unnoticed.
        """
        try:
            if self._repo.head_is_detached:
                return "HEAD"
            return str(self._repo.head.shorthand)
        except pygit2.GitError:
            return "HEAD"

    def get_repo_root(self) -> Path:
        """Get the root directory of the git repository."""
        return Path(self._repo.workdir)

    def stage_files(self, files: list[Path]) -> None:
        """Stage files for commit."""
        repo_root = self.get_repo_root()
        for file_path in files:
            # Make path relative to repo root
            if file_path.is_absolute():
                rel_path = file_path.relative_to(repo_root)
            else:
                rel_path = file_path
            self._repo.index.add(str(rel_path))
        self._repo.index.write()

    def _matches_pattern(self, tag_name: str, pattern: str) -> bool:
        """Check if a tag matches a glob pattern."""
        if pattern.endswith("*"):
            prefix = pattern.rstrip("*")
            return tag_name.startswith(prefix)
        return tag_name == pattern

    def _file_matches_filters(self, file_path: Path, filters: list[str]) -> bool:
        """Check if a file path matches any of the filter patterns."""
        for pattern in filters:
            if pattern == ".":
                return True

            pattern_path = Path(pattern)
            if pattern.endswith("**"):
                # Match directory prefix
                prefix = str(pattern_path.parent)
                if str(file_path).startswith(prefix):
                    return True
            elif str(file_path).startswith(str(pattern_path)):
                return True

        return False
