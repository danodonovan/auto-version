"""Tests for the real git backend, on real repositories.

Every other test in this suite uses ``MockGitRepository``. These cannot: what
they check is how a commit's *tree* is built, and a mock that records the
paths it was handed would agree with any implementation, including the one
that committed the whole index regardless. The repositories are created in
``tmp_path`` and are never pushed anywhere.
"""

from pathlib import Path

import pygit2
import pytest

from auto_version.git.pygit2_impl import PyGit2Repository


@pytest.fixture
def repo(tmp_path: Path) -> PyGit2Repository:
    """A repository with one commit, configured so commits can be signed."""
    handle = pygit2.init_repository(str(tmp_path), initial_head="main")
    config = handle.config
    config["user.name"] = "Test"
    config["user.email"] = "test@example.invalid"

    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')
    handle.index.add("pyproject.toml")
    handle.index.write()
    signature = handle.default_signature
    handle.create_commit(
        "HEAD", signature, signature, "initial", handle.index.write_tree(), []
    )

    return PyGit2Repository(tmp_path)


def _changed_paths(repo: PyGit2Repository, sha: str) -> set[str]:
    """Paths the commit ``sha`` changed relative to its first parent."""
    commit = repo._repo.revparse_single(sha)
    diff = repo._repo.diff(commit.parents[0], commit)
    return {delta.new_file.path for delta in diff.deltas}


def test_a_commit_contains_only_the_files_it_was_given(repo, tmp_path):
    """Work staged before the release must not ride along in it.

    The index held the release's files *and* a developer's half-finished
    change; committing ``index.write_tree()`` published both under a
    ``release:`` message.
    """
    (tmp_path / "unrelated.py").write_text("SECRET_WIP = 1\n")
    repo._repo.index.add("unrelated.py")
    repo._repo.index.write()

    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.1"\n')
    repo.stage_files([tmp_path / "pyproject.toml"])
    sha = repo.create_commit("release: 1.0.1", [tmp_path / "pyproject.toml"])

    assert _changed_paths(repo, sha) == {"pyproject.toml"}


def test_the_pre_staged_change_is_still_staged_afterwards(repo, tmp_path):
    """Excluding it from the commit must not unstage or discard it either."""
    (tmp_path / "unrelated.py").write_text("SECRET_WIP = 1\n")
    repo._repo.index.add("unrelated.py")
    repo._repo.index.write()

    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.1"\n')
    repo.stage_files([tmp_path / "pyproject.toml"])
    repo.create_commit("release: 1.0.1", [tmp_path / "pyproject.toml"])

    repo._repo.index.read(True)
    assert "unrelated.py" in repo._repo.index
    assert (tmp_path / "unrelated.py").read_text() == "SECRET_WIP = 1\n"


def test_unstaged_edits_to_a_release_file_are_committed(repo, tmp_path):
    """The release's own files are read from the worktree, not the index.

    ``release()`` writes them and hands over the paths; nothing guarantees an
    ``index.add`` ran for every one, and reading a stale index entry would
    commit the old version string.
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.1"\n')
    sha = repo.create_commit("release: 1.0.1", [Path("pyproject.toml")])

    blob = repo._repo.revparse_single(sha).tree["pyproject.toml"]
    assert b'version = "1.0.1"' in blob.data


def test_a_new_file_is_added_and_a_deleted_one_recorded_as_deleted(repo, tmp_path):
    """A changelog appears; a build command that removed an asset is honoured."""
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n")
    added = repo.create_commit("release: 1.0.1", [tmp_path / "CHANGELOG.md"])
    assert _changed_paths(repo, added) == {"CHANGELOG.md"}

    (tmp_path / "CHANGELOG.md").unlink()
    removed = repo.create_commit("release: 1.0.2", [tmp_path / "CHANGELOG.md"])
    assert "CHANGELOG.md" not in repo._repo.revparse_single(removed).tree


def test_an_executable_bit_survives_a_release_that_rewrites_the_file(repo, tmp_path):
    """Rebuilding the entry must not silently drop the mode git had."""
    script = tmp_path / "run.sh"
    script.write_text("#!/bin/sh\necho 1\n")
    script.chmod(0o755)
    first = repo.create_commit("chore: add script", [script])
    assert repo._repo.revparse_single(first).tree["run.sh"].filemode == (
        pygit2.GIT_FILEMODE_BLOB_EXECUTABLE
    )

    script.write_text("#!/bin/sh\necho 2\n")
    second = repo.create_commit("release: 1.0.1", [script])
    assert repo._repo.revparse_single(second).tree["run.sh"].filemode == (
        pygit2.GIT_FILEMODE_BLOB_EXECUTABLE
    )


def test_the_first_commit_in_a_repository_still_works(tmp_path):
    """An unborn HEAD has no tree to build on; the commit is the whole tree."""
    handle = pygit2.init_repository(str(tmp_path), initial_head="main")
    handle.config["user.name"] = "Test"
    handle.config["user.email"] = "test@example.invalid"
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')

    repo = PyGit2Repository(tmp_path)
    sha = repo.create_commit("release: 0.1.0", [tmp_path / "pyproject.toml"])

    tree = repo._repo.revparse_single(sha).tree
    assert [entry.name for entry in tree] == ["pyproject.toml"]
