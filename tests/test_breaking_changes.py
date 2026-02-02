"""Tests for breaking change detection and version bumping."""

from datetime import datetime, timezone
from pathlib import Path

from auto_version.analysis.commit_parser import parse_conventional_commit
from auto_version.analysis.version_calculator import calculate_version_bump
from auto_version.config import CommitParserOptions
from auto_version.models import CommitInfo, VersionBump


def test_parse_breaking_change_with_exclamation():
    """Test parsing commit with breaking change marker (!)."""
    commit = CommitInfo(
        sha="abc123",
        short_sha="abc123",
        message="feat!: breaking change description",
        commit_type="",
        scope=None,
        description="",
        body="",
        timestamp=datetime.now(timezone.utc),
        affected_files=[],
    )

    parsed = parse_conventional_commit(commit)

    assert parsed.commit_type == "feat"
    assert parsed.breaking is True
    assert parsed.description == "breaking change description"


def test_parse_breaking_change_in_body():
    """Test parsing commit with BREAKING CHANGE in body."""
    commit = CommitInfo(
        sha="abc123",
        short_sha="abc123",
        message="feat: add new feature\n\nBREAKING CHANGE: this breaks something",
        commit_type="",
        scope=None,
        description="",
        body="BREAKING CHANGE: this breaks something",
        timestamp=datetime.now(timezone.utc),
        affected_files=[],
    )

    parsed = parse_conventional_commit(commit)

    assert parsed.commit_type == "feat"
    assert parsed.breaking is True
    assert parsed.description == "add new feature"


def test_parse_breaking_change_with_hyphen():
    """Test parsing commit with BREAKING-CHANGE in body."""
    commit = CommitInfo(
        sha="abc123",
        short_sha="abc123",
        message="fix: fix bug\n\nBREAKING-CHANGE: this breaks something",
        commit_type="",
        scope=None,
        description="",
        body="BREAKING-CHANGE: this breaks something",
        timestamp=datetime.now(timezone.utc),
        affected_files=[],
    )

    parsed = parse_conventional_commit(commit)

    assert parsed.commit_type == "fix"
    assert parsed.breaking is True


def test_breaking_change_triggers_major_bump():
    """Test that breaking changes trigger major version bump."""
    options = CommitParserOptions(
        minor_tags=["feat"],
        patch_tags=["fix"],
        major_tags=[],  # Empty - breaking changes should still trigger major
    )

    commits = [
        CommitInfo(
            sha="abc123",
            short_sha="abc123",
            message="feat!: breaking change",
            commit_type="feat",
            scope=None,
            description="breaking change",
            body="",
            timestamp=datetime.now(timezone.utc),
            affected_files=[],
            breaking=True,
        )
    ]

    bump = calculate_version_bump(commits, options)
    assert bump == VersionBump.MAJOR


def test_breaking_change_with_fix_triggers_major():
    """Test that breaking changes in fix commits trigger major bump."""
    options = CommitParserOptions(
        minor_tags=["feat"],
        patch_tags=["fix"],
        major_tags=[],
    )

    commits = [
        CommitInfo(
            sha="abc123",
            short_sha="abc123",
            message="fix!: breaking fix",
            commit_type="fix",
            scope=None,
            description="breaking fix",
            body="",
            timestamp=datetime.now(timezone.utc),
            affected_files=[],
            breaking=True,
        )
    ]

    bump = calculate_version_bump(commits, options)
    assert bump == VersionBump.MAJOR


def test_mixed_with_breaking_change_triggers_major():
    """Test that breaking changes override other bump types."""
    options = CommitParserOptions(
        minor_tags=["feat"],
        patch_tags=["fix"],
        major_tags=[],
    )

    commits = [
        CommitInfo(
            sha="abc123",
            short_sha="abc123",
            message="fix: normal fix",
            commit_type="fix",
            scope=None,
            description="normal fix",
            body="",
            timestamp=datetime.now(timezone.utc),
            affected_files=[],
            breaking=False,
        ),
        CommitInfo(
            sha="def456",
            short_sha="def456",
            message="feat: new feature",
            commit_type="feat",
            scope=None,
            description="new feature",
            body="",
            timestamp=datetime.now(timezone.utc),
            affected_files=[],
            breaking=False,
        ),
        CommitInfo(
            sha="ghi789",
            short_sha="ghi789",
            message="feat!: breaking feature",
            commit_type="feat",
            scope=None,
            description="breaking feature",
            body="",
            timestamp=datetime.now(timezone.utc),
            affected_files=[],
            breaking=True,
        ),
    ]

    bump = calculate_version_bump(commits, options)
    assert bump == VersionBump.MAJOR
