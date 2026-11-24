# auto-version

Automatic release management for Python monorepos based on conventional commits.

## Features

- 🏷️ Automatic semantic versioning from conventional commits
- 🧪 PEP 440 pre-releases (`1.0.0b1`, `1.0.0rc2`): start, iterate, and graduate beta lines
- 📝 Changelog generation with GitHub links
- 🎯 Path-based filtering for monorepo support
- 🧪 Fully testable with dry-run mode
- ⚡ Fast and simple (unlike python-semantic-release for monorepos)

## Installation

```bash
pip install auto-version
```

## Quick Start

```bash
# Release a package
auto-version release packages/mypackage/pyproject.toml

# Dry run to see what would happen
auto-version release packages/mypackage/pyproject.toml --dry-run

# From within a package directory
cd packages/mypackage
auto-version release
```

## Configuration

Add to your `pyproject.toml`:

```toml
[tool.auto_version]
tag_format = "mypackage-{version}"
version_variables = ["mypackage/__init__.py:__version__"]
version_toml = ["pyproject.toml:project.version"]
commit_message = "release: mypackage {version}"
path_filters = ["."]

[tool.auto_version.commit_parser_options]
minor_tags = ["feat"]
patch_tags = ["fix", "perf", "docs", "build", "ci"]
```

## How It Works

1. Finds the latest git tag matching your `tag_format`
2. Analyzes conventional commits since that tag
3. Calculates the next semantic version
4. Updates version in configured files
5. Updates CHANGELOG.md
6. Creates a release commit and tag

## Pre-releases

`auto-version` understands [PEP 440](https://peps.python.org/pep-0440/) pre-releases
(`1.0.0a1`, `1.0.0b1`, `1.0.0rc2`) and orders them correctly
(`1.0.0a1 < 1.0.0b1 < 1.0.0b2 < 1.0.0rc1 < 1.0.0 < 1.0.1`), so a manually-cut beta is
never silently overwritten by a normal release.

Two optional config keys control the workflow. When both are absent, behaviour is
identical to a normal `X.Y.Z` project.

```toml
[tool.auto_version]
prerelease_token = "b"     # active channel: "a" | "b" | "rc". When set, releases are cut as pre-releases.
release_as = "1.0.0"       # force the base release for the next release; needed only to *start* a line.
```

The release each run depends on the current state:

| Current state | Config | Next release |
|---|---|---|
| **Start** a line (base is `0.11.0`) | `prerelease_token = "b"`, `release_as = "1.0.0"` | `1.0.0b0` |
| **Iterate** (base is `1.0.0b1`) | `prerelease_token = "b"` | `1.0.0b2` |
| **Change channel** (base is `1.0.0b3`) | `prerelease_token = "rc"` | `1.0.0rc0` |
| **Graduate** (base is `1.0.0b2`) | *(token removed)* | `1.0.0` |
| **Normal** (base is `0.11.0`) | *(no token)* | `0.12.0` |

Typical lifecycle: set `prerelease_token = "b"` (plus `release_as` once, to start), let merges
cut `b1`, `b2`, … as commits land, then remove `prerelease_token` to graduate to the final
`1.0.0`. After graduation, normal `X.Y.Z` bumping resumes.

> A release only happens when there are release-worthy commits. With no such commits,
> `auto-version` exits `2` (no changes) in every mode, including the pre-release modes.

## auto-version releases itself

This repository is configured under `[tool.auto_version]` in its own
`pyproject.toml`, and `.github/workflows/release.yml` runs
`auto-version release --push --branch main` on every push to `main`. The tool
is installed from the commit being released (`pip install -e .`), so a change
to the release path is exercised by the release that ships it — and every
release is a live end-to-end test of `--push` against a real remote.

`CHANGELOG.md` was backfilled for `0.1.0` and `0.2.0`, which were tagged by
hand before this was wired up.

## License

MIT
