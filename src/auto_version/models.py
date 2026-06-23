"""Core data models."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from packaging.version import InvalidVersion
from packaging.version import Version as _PackagingVersion


class VersionBump(Enum):
    """Type of version bump."""

    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"
    NONE = "none"


@dataclass(frozen=True)
class Version:
    """A PEP 440-aware version.

    Stores the release segment as ``(major, minor, patch)`` plus an optional
    pre-release ``pre`` of the form ``("a" | "b" | "rc", N)`` (the PEP 440
    normalised spelling). Parsing, rendering, and ordering are delegated to
    ``packaging.version.Version`` so that pre-releases sort correctly, e.g.
    ``1.0.0a1 < 1.0.0b1 < 1.0.0b2 < 1.0.0rc1 < 1.0.0 < 1.0.1``.
    """

    major: int
    minor: int
    patch: int
    pre: tuple[str, int] | None = None

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.pre is not None:
            return f"{base}{self.pre[0]}{self.pre[1]}"
        return base

    @classmethod
    def parse(cls, version_str: str) -> "Version":
        """Parse a PEP 440 version string like '1.2.3', 'v1.2.3', or '1.0.0b1'.

        Raises ValueError on genuinely malformed input.
        """
        try:
            parsed = _PackagingVersion(version_str)
        except InvalidVersion as e:
            raise ValueError(f"Invalid version format: {version_str}") from e

        # Pad the release segment to (major, minor, patch).
        release = tuple(parsed.release) + (0, 0, 0)
        major, minor, patch = release[0], release[1], release[2]

        # packaging normalises the pre-release letter to one of "a"/"b"/"rc".
        pre = (parsed.pre[0], parsed.pre[1]) if parsed.pre is not None else None

        return cls(major, minor, patch, pre)

    @classmethod
    def from_string(cls, version_str: str) -> "Version":
        """Alias for parse() - parse a PEP 440 version string."""
        return cls.parse(version_str)

    @property
    def is_prerelease(self) -> bool:
        """True if this version carries a pre-release segment."""
        return self.pre is not None

    def base_version(self) -> "Version":
        """Return this version with any pre-release dropped (e.g. 1.0.0b2 -> 1.0.0)."""
        return Version(self.major, self.minor, self.patch)

    def with_prerelease(self, token: str, num: int) -> "Version":
        """Return this version's release segment with the given pre-release applied."""
        return Version(self.major, self.minor, self.patch, (token, num))

    def bump(self, bump_type: VersionBump) -> "Version":
        """Return a new (final) version with the specified bump applied.

        Always drops any pre-release; the pre-release decision lives in the
        release orchestration, not here.
        """
        if bump_type == VersionBump.MAJOR:
            return Version(self.major + 1, 0, 0)
        elif bump_type == VersionBump.MINOR:
            return Version(self.major, self.minor + 1, 0)
        elif bump_type == VersionBump.PATCH:
            return Version(self.major, self.minor, self.patch + 1)
        else:  # NONE
            return self.base_version()

    def _packaging(self) -> _PackagingVersion:
        return _PackagingVersion(str(self))

    def __lt__(self, other: "Version") -> bool:
        return self._packaging() < other._packaging()

    def __le__(self, other: "Version") -> bool:
        return self._packaging() <= other._packaging()

    def __gt__(self, other: "Version") -> bool:
        return self._packaging() > other._packaging()

    def __ge__(self, other: "Version") -> bool:
        return self._packaging() >= other._packaging()


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
