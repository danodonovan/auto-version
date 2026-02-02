"""Core data models."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class VersionBump(Enum):
    """Type of version bump."""

    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"
    NONE = "none"


@dataclass(frozen=True)
class Version:
    """Semantic version."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, version_str: str) -> "Version":
        """Parse version string like '1.2.3' or 'v1.2.3'."""
        version_str = version_str.lstrip("v")
        parts = version_str.split(".")
        if len(parts) != 3:
            raise ValueError(f"Invalid version format: {version_str}")
        try:
            return cls(int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError as e:
            raise ValueError(f"Invalid version format: {version_str}") from e

    @classmethod
    def from_string(cls, version_str: str) -> "Version":
        """Alias for parse() - parse version string like '1.2.3' or 'v1.2.3'."""
        return cls.parse(version_str)

    def bump(self, bump_type: VersionBump) -> "Version":
        """Return a new version with the specified bump applied."""
        if bump_type == VersionBump.MAJOR:
            return Version(self.major + 1, 0, 0)
        elif bump_type == VersionBump.MINOR:
            return Version(self.major, self.minor + 1, 0)
        elif bump_type == VersionBump.PATCH:
            return Version(self.major, self.minor, self.patch + 1)
        else:  # NONE
            return self

    def __lt__(self, other: "Version") -> bool:
        return (self.major, self.minor, self.patch) < (
            other.major,
            other.minor,
            other.patch,
        )

    def __le__(self, other: "Version") -> bool:
        return (self.major, self.minor, self.patch) <= (
            other.major,
            other.minor,
            other.patch,
        )

    def __gt__(self, other: "Version") -> bool:
        return (self.major, self.minor, self.patch) > (
            other.major,
            other.minor,
            other.patch,
        )

    def __ge__(self, other: "Version") -> bool:
        return (self.major, self.minor, self.patch) >= (
            other.major,
            other.minor,
            other.patch,
        )


@dataclass(frozen=True)
class CommitInfo:
    """Information about a parsed commit."""

    sha: str
    short_sha: str
    message: str
    commit_type: str  # feat, fix, docs, etc.
    scope: str | None
    description: str
    body: str
    timestamp: datetime
    affected_files: list[Path]
    breaking: bool = False  # True if commit contains breaking changes

    @property
    def is_conventional(self) -> bool:
        """Check if this is a valid conventional commit."""
        return bool(self.commit_type)


@dataclass(frozen=True)
class ReleaseResult:
    """Result of a release operation."""

    package_name: str
    old_version: Version
    new_version: Version
    bump_type: VersionBump
    tag: str
    commit_sha: str
    commits_included: list[CommitInfo]
    dry_run: bool
