# Example Usage

This directory contains an example of how to use auto-version.

## Setup

The example package is configured in `pyproject.toml`:

```toml
[tool.auto_version]
tag_format = "example-{version}"
version_toml = ["pyproject.toml:project.version"]
version_variables = ["example/__init__.py:__version__"]
commit_message = "release: example {version}"
path_filters = ["."]
github_repo = "owner/repo"

[tool.auto_version.commit_parser_options]
minor_tags = ["feat"]
patch_tags = ["fix", "perf", "docs", "build", "ci"]
```

## Usage

```bash
# Check status (dry run)
cd example
auto-version release --dry-run

# Create a release
auto-version release

# Check status
auto-version status
```

## Typical Workflow

1. Make changes to your package
2. Commit using conventional commit messages:
   - `feat: add new feature` (minor bump)
   - `fix: correct bug` (patch bump)
3. Run `auto-version release` to create a release
4. Push: `git push && git push --tags`
