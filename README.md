# auto-version

Automatic release management for Python monorepos based on conventional commits.

## Features

- 🏷️ Automatic semantic versioning from conventional commits
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

## License

MIT
