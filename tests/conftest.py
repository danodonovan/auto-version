"""Pytest fixtures for tests."""

from datetime import datetime
from pathlib import Path

import pytest

from auto_version.git.mock_impl import MockGitRepository
from auto_version.models import CommitInfo


@pytest.fixture
def mock_repo() -> MockGitRepository:
    """Create a mock git repository."""
    return MockGitRepository(repo_root=Path("/test/repo"))


@pytest.fixture
def simple_commit() -> CommitInfo:
    """Create a simple commit for testing."""
    return CommitInfo(
        sha="abc123def456",
        short_sha="abc123d",
        message="feat: add new feature",
        commit_type="feat",
        scope=None,
        description="add new feature",
        body="",
        timestamp=datetime.now(),
        affected_files=[Path("src/main.py")],
    )
