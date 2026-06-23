# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

`auto-version` is a lightweight Python CLI for automatic release management in monorepos using conventional commits. It detects version bumps from commit history, updates version strings in files, generates changelogs, and creates git tags — designed as a simpler alternative to `python-semantic-release` with native monorepo support.

## Commands

```bash
# Install for development
pip install -e ".[dev]"

# Run tests
make test
# or
pytest tests/ -v

# Run a single test file
pytest tests/test_commit_parser.py -v

# Run with coverage
pytest tests/ --cov=auto_version --cov-report=html

# Format code
make fix

# CLI usage
auto-version release [CONFIG_PATH] [--dry-run] [--verbose]
auto-version status [CONFIG_PATH]
auto-version show-version [CONFIG_PATH]
```

## Architecture

The project follows a clean layered architecture:

```
CLI (cli.py)
  └─> ReleaseOrchestrator (orchestration/release.py)
        ├─> Git layer (git/interface.py + pygit2_impl.py / mock_impl.py)
        ├─> Analysis layer (analysis/commit_parser.py + version_calculator.py)
        ├─> Versioning layer (versioning/updater.py + reader.py)
        └─> Changelog layer (changelog/generator.py)
```

**Key design decisions:**
- `GitRepository` is an abstract interface — `PyGit2Repository` handles real git ops; `MockGitRepository` (in-memory) is used in all tests. Never instantiate a real git repo in tests.
- Data models (`models.py`) are frozen dataclasses — `Version`, `CommitInfo`, `ReleaseResult`.
- Analysis modules (`commit_parser`, `version_calculator`) are pure functions with no side effects.
- CLI exit codes: 0 = success, 1 = error, 2 = no changes needed, 3 = validation error.

## Configuration

Each package is configured in its own `pyproject.toml` under `[tool.auto_version]`:

```toml
[tool.auto_version]
tag_format = "mypackage-{version}"                    # required; used to find latest tag
version_toml = ["pyproject.toml:project.version"]     # dot-separated key path into TOML
version_variables = ["pkg/__init__.py:__version__"]   # Python variable to regex-replace
path_filters = ["."]                                  # commit path filter for monorepo isolation
changelog_path = "CHANGELOG.md"
github_repo = "owner/repo"
```

Version bump priority: `MAJOR` (breaking `!` or `BREAKING CHANGE:` in body) > `MINOR` (feat) > `PATCH` (fix, perf, docs, etc.) > `NONE`. Non-conventional commits count as PATCH.

## Testing Approach

Tests use `MockGitRepository` (never real git). Fixtures are in `tests/conftest.py`:
- `mock_repo` — a fresh `MockGitRepository` instance
- `simple_commit` — a standard `CommitInfo` fixture

The `example/` directory contains a working package config that doubles as a manual integration test target.
