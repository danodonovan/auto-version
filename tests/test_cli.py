"""Exit codes the CLI promises for `release --push` validation failures."""

from datetime import datetime, timezone
from pathlib import Path

from click.testing import CliRunner

from auto_version import cli
from auto_version.git.mock_impl import MockGitRepository
from auto_version.models import CommitInfo


def test_negative_push_retries_exits_3_not_2(tmp_path: Path, monkeypatch) -> None:
    """A bad retry count is a validation error (3), not Click's usage error (2).

    Exit 2 is documented as "no release needed", so a script checking for it
    could mistake a typo for a no-op release. `click.IntRange` rejected the
    value during parsing and exited 2; the orchestrator already validates the
    count and raises ValueError, which the CLI maps to 3. No real repository is
    created: the pygit2 implementation is swapped for the mock.
    """
    config = tmp_path / "pyproject.toml"
    config.write_text(
        '[project]\nname = "kg"\nversion = "1.0.0"\n\n'
        '[tool.auto_version]\ntag_format = "kg-{version}"\n'
        'version_toml = ["pyproject.toml:project.version"]\n'
    )
    monkeypatch.setattr(
        cli, "PyGit2Repository", lambda root: MockGitRepository(repo_root=root)
    )

    result = CliRunner().invoke(
        cli.main, ["release", str(config), "--push", "--push-retries", "-1"]
    )

    assert result.exit_code == 3, result.output
    assert "zero or greater" in result.output


def test_a_bare_release_warns_about_build_command_leftovers(
    tmp_path: Path, monkeypatch
) -> None:
    """Plain `release` still succeeds, but must not stay silent about a leak.

    `--push` refuses to publish while leftovers are present, so a build command
    that leaks passes here and fails the moment someone adds the flag. Saying so
    at the point the files appear is the difference between a config fix and a
    CI mystery.
    """
    config = tmp_path / "pyproject.toml"
    config.write_text(
        '[project]\nname = "kg"\nversion = "1.0.0"\n\n'
        '[tool.auto_version]\ntag_format = "kg-{version}"\n'
        'version_toml = ["pyproject.toml:project.version"]\n'
        'build_command = "touch stray.leak"\n'
    )

    def repo_for(root: Path) -> MockGitRepository:
        repo = MockGitRepository(repo_root=root)
        repo.add_commit(
            CommitInfo(
                sha="fix1",
                short_sha="fix1",
                message="fix: a fix",
                commit_type="fix",
                scope=None,
                description="a fix",
                body="",
                timestamp=datetime.now(timezone.utc),
                affected_files=[Path("kg/thing.py")],
            )
        )
        repo.dirty_paths = lambda: [p.name for p in root.glob("*.leak")]  # type: ignore[method-assign]
        return repo

    monkeypatch.setattr(cli, "PyGit2Repository", repo_for)

    result = CliRunner().invoke(cli.main, ["release", str(config)])

    assert result.exit_code == 0, result.output
    assert "stray.leak" in result.output
    assert 'assets = ["stray.leak"]' in result.output
