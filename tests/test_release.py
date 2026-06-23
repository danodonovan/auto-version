"""Tests for the release orchestration, focused on pre-release version computation.

All tests use MockGitRepository (never real git) and run releases in dry-run mode,
so no files are touched — we assert on the computed new version / bump type only.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from auto_version.config import Config
from auto_version.git.mock_impl import MockGitRepository
from auto_version.models import CommitInfo, VersionBump
from auto_version.orchestration.release import ReleaseOrchestrator


def _make_config(
    prerelease_token: str | None = None, release_as: str | None = None
) -> Config:
    return Config(
        tag_format="dwpc-{version}",
        version_toml=["pyproject.toml:project.version"],
        path_filters=["."],
        prerelease_token=prerelease_token,
        release_as=release_as,
    )


def _feat_commit(sha: str) -> CommitInfo:
    return CommitInfo(
        sha=sha,
        short_sha=sha[:7],
        message="feat: add a feature",
        commit_type="feat",
        scope=None,
        description="add a feature",
        body="",
        timestamp=datetime.now(timezone.utc),
        affected_files=[Path("dwpc/thing.py")],
        breaking=False,
    )


def _repo_with(base_tags: list[str], releasable: bool = True) -> MockGitRepository:
    """Build a mock repo: a base commit, the given tags on it, then optional feat commit."""
    repo = MockGitRepository(repo_root=Path("/test/repo"))
    repo.add_commit(
        CommitInfo(
            sha="base",
            short_sha="base",
            message="chore: base",
            commit_type="chore",
            scope=None,
            description="base",
            body="",
            timestamp=datetime.now(timezone.utc),
            affected_files=[Path("dwpc/base.py")],
        )
    )
    for tag in base_tags:
        repo.add_tag(tag, "base")
    if releasable:
        repo.add_commit(_feat_commit("feat1"))
    return repo


def _release(repo: MockGitRepository, config: Config):
    return ReleaseOrchestrator(repo, config).release(dry_run=True)


# --- discovery ---


def test_find_latest_tag_picks_highest_prerelease():
    """Pre-release tags are no longer skipped; PEP 440 ordering wins."""
    repo = _repo_with(["dwpc-0.11.0", "dwpc-1.0.0b0", "dwpc-1.0.0b1"])
    orchestrator = ReleaseOrchestrator(repo, _make_config(prerelease_token="b"))
    assert orchestrator._find_latest_tag() == "dwpc-1.0.0b1"
    assert str(orchestrator.get_latest_version()) == "1.0.0b1"


# --- workflow cases (with releasable commits) ---


def test_start_line_with_release_as():
    """token=b, release_as=1.0.0, base 0.11.0 -> 1.0.0b0."""
    repo = _repo_with(["dwpc-0.11.0"])
    result = _release(repo, _make_config(prerelease_token="b", release_as="1.0.0"))
    assert str(result.new_version) == "1.0.0b0"


def test_iterate_line():
    """token=b, base 1.0.0b1 -> 1.0.0b2."""
    repo = _repo_with(["dwpc-1.0.0b1"])
    result = _release(repo, _make_config(prerelease_token="b"))
    assert str(result.new_version) == "1.0.0b2"


def test_iterate_line_with_collision():
    """token=b, tags b1 and b2 exist -> next is b3 (collision-safe)."""
    repo = _repo_with(["dwpc-1.0.0b1", "dwpc-1.0.0b2"])
    result = _release(repo, _make_config(prerelease_token="b"))
    assert str(result.new_version) == "1.0.0b3"


def test_channel_change_resets_number():
    """token=rc, base 1.0.0b3 -> 1.0.0rc0."""
    repo = _repo_with(["dwpc-1.0.0b3"])
    result = _release(repo, _make_config(prerelease_token="rc"))
    assert str(result.new_version) == "1.0.0rc0"


def test_graduate():
    """token unset, base 1.0.0b2 -> 1.0.0."""
    repo = _repo_with(["dwpc-1.0.0b2"])
    result = _release(repo, _make_config())
    assert str(result.new_version) == "1.0.0"


def test_normal_bump_unchanged():
    """token unset, base 0.11.0, feat -> 0.12.0 (regression guard)."""
    repo = _repo_with(["dwpc-0.11.0"])
    result = _release(repo, _make_config())
    assert str(result.new_version) == "0.12.0"
    assert result.bump_type == VersionBump.MINOR


# --- no releasable commits => NONE in every mode (CI relies on this) ---


@pytest.mark.parametrize(
    "config",
    [
        _make_config(),
        _make_config(prerelease_token="b"),
        _make_config(prerelease_token="b", release_as="1.0.0"),
    ],
)
def test_no_releasable_commits_is_none(config):
    """With no commits since the tag, bump is NONE regardless of pre-release mode."""
    repo = _repo_with(["dwpc-1.0.0b1"], releasable=False)
    result = _release(repo, config)
    assert result.bump_type == VersionBump.NONE
    assert result.new_version == result.old_version


# --- rendering: pre-release flows through to the ReleaseResult/tag ---


def test_prerelease_renders_in_tag_and_result():
    """The computed pre-release renders in the result tag string."""
    repo = _repo_with(["dwpc-1.0.0b1"])
    result = _release(repo, _make_config(prerelease_token="b"))
    assert result.tag == "dwpc-1.0.0b2"
    assert str(result.new_version) == "1.0.0b2"


def test_prerelease_renders_through_version_files_and_changelog(tmp_path):
    """The 'unchanged' versioning/changelog modules emit the pre-release string."""
    from auto_version.changelog.generator import update_changelog
    from auto_version.models import Version
    from auto_version.versioning.updater import update_version_files

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "dwpc"\nversion = "0.11.0"\n'
    )
    (tmp_path / "dwpc").mkdir()
    (tmp_path / "dwpc" / "__init__.py").write_text('__version__ = "0.11.0"\n')

    new_version = Version.parse("1.0.0b2")
    update_version_files(
        version_toml=["pyproject.toml:project.version"],
        version_variables=["dwpc/__init__.py:__version__"],
        new_version=new_version,
        package_root=tmp_path,
    )
    assert 'version = "1.0.0b2"' in (tmp_path / "pyproject.toml").read_text()
    assert '__version__ = "1.0.0b2"' in (tmp_path / "dwpc" / "__init__.py").read_text()

    changelog_path = tmp_path / "CHANGELOG.md"
    update_changelog(changelog_path, new_version, commits=[_feat_commit("feat1")])
    assert "## v1.0.0b2" in changelog_path.read_text()
