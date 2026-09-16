"""Exit codes the CLI promises for `release --push` validation failures."""

from pathlib import Path

from click.testing import CliRunner

from auto_version import cli
from auto_version.git.mock_impl import MockGitRepository


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
