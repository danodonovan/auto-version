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
auto-version release --push [--remote origin] [--branch main] [--push-retries 3]
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
- CLI exit codes: 0 = success, 1 = error, 2 = no changes needed, 3 = validation error,
  4 = push rejected (see `--push` below).

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
prerelease_token = "b"                                # optional: "a" | "b" | "rc"; cut releases on this channel
release_as = "1.0.0"                                  # optional: force the base release (to start a line)
```

Version bump priority: `MAJOR` (breaking `!` or `BREAKING CHANGE:` in body) > `MINOR` (feat) > `PATCH` (fix, perf, docs, etc.) > `NONE`. Non-conventional commits count as PATCH.

### Pre-releases (PEP 440)

`Version` is PEP 440-aware (backed by the `packaging` dependency): it parses, orders, and renders pre-releases (`1.0.0a1`, `1.0.0b1`, `1.0.0rc2`) in normalised form. Ordering is true PEP 440 — `1.0.0a1 < 1.0.0b1 < 1.0.0b2 < 1.0.0rc1 < 1.0.0 < 1.0.1` — so pre-release tags are no longer skipped by `_find_latest_tag` and can never be silently trampled.

The two optional config keys above (absent ⇒ standard `X.Y.Z` behaviour, byte-for-byte) drive `ReleaseOrchestrator._compute_new_version`, which has four cases:
- **Start** — `prerelease_token` set and base is final (or `release_as` forces it): `release_as or base.bump(...)` → `…b0`.
- **Iterate** — token set, base is a pre-release on the same token: `…b1 → …b2` (base release fixed; collision-safe via `_next_prerelease_number`, which picks `max+1`).
- **Channel change** — token set, base is a pre-release on a different token: `1.0.0b3 → 1.0.0rc0`.
- **Graduate** — token unset, base is a pre-release: drop the pre-release (`1.0.0b2 → 1.0.0`); normal bumping resumes after.

`show-version` resolves the latest tag through PEP 440 ordering (`orchestrator.get_latest_version()`), not the raw `get_tags()[0]` order.

## Testing Approach

Tests use `MockGitRepository` (never real git). Fixtures are in `tests/conftest.py`:
- `mock_repo` — a fresh `MockGitRepository` instance
- `simple_commit` — a standard `CommitInfo` fixture

`MockGitRepository` is both a builder and a spy: set up state with `add_commit()` / `add_tag()`, then assert on the git operations that ran via `get_operations()` (logs entries like `create_tag: …`, `create_commit: …`, `stage_files: …`, `push: …`, `fetch: …`, `reset_hard: …`, `delete_tag: …`). Use this to verify orchestration behavior without mutating a real repo.

For publication (`release_and_publish`), the mock also simulates contention and
the states `--push` must refuse:
- `queue_push_failures(count, non_fast_forward=True)` — make the next `count` pushes raise `PushRejected`
- `add_release_arriving_on_fetch(commit, tag=None)` — reveal the winning job's release (its commit, and optionally its tag) on the next `fetch()`
- `set_dirty(True)` — report tracked modifications
- `set_current_branch(None)` — model a detached HEAD
- `fail_tag_delete(name)` — make `delete_tag` raise, as a ref lock would
- `set_diverged_from_remote(True)` — model a branch carrying commits the remote lacks

`add_release_arriving_on_fetch(commit, tag)` adds the winner's commit **and** tag. Registering a tag without its commit leaves `get_commits_since` unable to resolve it, so the mock reports all history as unreleased and a recomputed version passes for the wrong reason.

Pass `sleep=lambda _: None` to `release_and_publish` in tests so the backoff does not slow the suite. See `tests/test_publish.py`.

The `example/` directory contains a working package config that doubles as a manual integration test target.
