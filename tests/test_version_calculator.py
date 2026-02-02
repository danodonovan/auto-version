"""Tests for version calculation."""

from datetime import datetime
from pathlib import Path

from auto_version.analysis.version_calculator import calculate_version_bump
from auto_version.config import CommitParserOptions
from auto_version.models import CommitInfo, VersionBump


def test_calculate_version_bump_empty():
    """Test version bump with no commits."""
    options = CommitParserOptions()
    bump = calculate_version_bump([], options)
    assert bump == VersionBump.NONE


def test_calculate_version_bump_minor():
    """Test version bump with feature commits."""
    options = CommitParserOptions(minor_tags=["feat"], patch_tags=["fix"])

    commits = [
        CommitInfo(
            sha="abc123",
            short_sha="abc123",
            message="feat: add feature",
            commit_type="feat",
            scope=None,
            description="add feature",
            body="",
            timestamp=datetime.now(),
            affected_files=[Path("src/main.py")],
        )
    ]

    bump = calculate_version_bump(commits, options)
    assert bump == VersionBump.MINOR


def test_calculate_version_bump_patch():
    """Test version bump with fix commits."""
    options = CommitParserOptions(minor_tags=["feat"], patch_tags=["fix"])

    commits = [
        CommitInfo(
            sha="abc123",
            short_sha="abc123",
            message="fix: correct bug",
            commit_type="fix",
            scope=None,
            description="correct bug",
            body="",
            timestamp=datetime.now(),
            affected_files=[Path("src/main.py")],
        )
    ]

    bump = calculate_version_bump(commits, options)
    assert bump == VersionBump.PATCH


def test_calculate_version_bump_mixed():
    """Test version bump with mixed commit types (should choose highest)."""
    options = CommitParserOptions(minor_tags=["feat"], patch_tags=["fix"])

    commits = [
        CommitInfo(
            sha="abc123",
            short_sha="abc123",
            message="fix: bug fix",
            commit_type="fix",
            scope=None,
            description="bug fix",
            body="",
            timestamp=datetime.now(),
            affected_files=[Path("src/main.py")],
        ),
        CommitInfo(
            sha="def456",
            short_sha="def456",
            message="feat: new feature",
            commit_type="feat",
            scope=None,
            description="new feature",
            body="",
            timestamp=datetime.now(),
            affected_files=[Path("src/feature.py")],
        ),
    ]

    bump = calculate_version_bump(commits, options)
    assert bump == VersionBump.MINOR  # feat > fix


def test_calculate_version_bump_non_conventional():
    """Test version bump with non-conventional commits (treated as patch)."""
    options = CommitParserOptions(minor_tags=["feat"], patch_tags=["fix"])

    commits = [
        CommitInfo(
            sha="abc123",
            short_sha="abc123",
            message="just a commit",
            commit_type="",
            scope=None,
            description="just a commit",
            body="",
            timestamp=datetime.now(),
            affected_files=[Path("src/main.py")],
        )
    ]

    bump = calculate_version_bump(commits, options)
    assert bump == VersionBump.PATCH
