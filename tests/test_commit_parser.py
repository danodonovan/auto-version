"""Tests for conventional commit parsing."""

from datetime import datetime
from pathlib import Path

from auto_version.analysis.commit_parser import parse_conventional_commit
from auto_version.models import CommitInfo


def test_parse_conventional_commit_feat():
    """Test parsing a feature commit."""
    commit = CommitInfo(
        sha="abc123",
        short_sha="abc123",
        message="feat: add new feature",
        commit_type="",
        scope=None,
        description="feat: add new feature",
        body="",
        timestamp=datetime.now(),
        affected_files=[Path("src/main.py")],
    )

    parsed = parse_conventional_commit(commit)
    assert parsed.commit_type == "feat"
    assert parsed.scope is None
    assert parsed.description == "add new feature"
    assert parsed.is_conventional


def test_parse_conventional_commit_with_scope():
    """Test parsing a commit with scope."""
    commit = CommitInfo(
        sha="abc123",
        short_sha="abc123",
        message="fix(api): correct endpoint",
        commit_type="",
        scope=None,
        description="fix(api): correct endpoint",
        body="",
        timestamp=datetime.now(),
        affected_files=[Path("src/api.py")],
    )

    parsed = parse_conventional_commit(commit)
    assert parsed.commit_type == "fix"
    assert parsed.scope == "api"
    assert parsed.description == "correct endpoint"


def test_parse_non_conventional_commit():
    """Test parsing a non-conventional commit."""
    commit = CommitInfo(
        sha="abc123",
        short_sha="abc123",
        message="just a regular commit message",
        commit_type="",
        scope=None,
        description="just a regular commit message",
        body="",
        timestamp=datetime.now(),
        affected_files=[Path("src/main.py")],
    )

    parsed = parse_conventional_commit(commit)
    assert parsed.commit_type == ""
    assert not parsed.is_conventional


def test_parse_commit_types():
    """Test parsing various commit types."""
    types = ["feat", "fix", "docs", "style", "refactor", "perf", "test", "chore"]

    for commit_type in types:
        commit = CommitInfo(
            sha="abc123",
            short_sha="abc123",
            message=f"{commit_type}: some change",
            commit_type="",
            scope=None,
            description=f"{commit_type}: some change",
            body="",
            timestamp=datetime.now(),
            affected_files=[Path("src/main.py")],
        )

        parsed = parse_conventional_commit(commit)
        assert parsed.commit_type == commit_type
        assert parsed.is_conventional
