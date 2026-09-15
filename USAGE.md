# Auto-Version Usage Guide

## Overview

Auto-version is a Python CLI tool for automatic release management in monorepos. It:
- Analyzes conventional commits since the last release
- Calculates semantic version bumps automatically
- Updates version in multiple file formats
- Generates/updates CHANGELOG.md
- Creates git commits and tags

## Installation

```bash
# From source
pip install -e .

# For development
pip install -e ".[dev]"
```

## Configuration

Add to your package's `pyproject.toml`:

```toml
[tool.auto_version]
# Required: Tag format with {version} placeholder
tag_format = "mypackage-{version}"

# Required: TOML files to update (format: "file:key.path")
version_toml = ["pyproject.toml:project.version"]

# Optional: Python files to update (format: "file:variable_name")
version_variables = ["mypackage/__init__.py:__version__"]

# Optional: Commit message template
commit_message = "release: mypackage {version}"

# Optional: Path filters (relative to package root)
path_filters = ["."]

# Optional: GitHub repo for commit links (owner/repo)
github_repo = "owner/repo"

# Optional: Changelog file path
changelog_path = "CHANGELOG.md"

[tool.auto_version.commit_parser_options]
# Commits that trigger minor version bumps
minor_tags = ["feat"]

# Commits that trigger patch version bumps
patch_tags = ["fix", "perf", "docs", "build", "ci"]

# Commits that trigger major version bumps (empty by default)
major_tags = []
```

## Commands

### Release

Create a new release for a package:

```bash
# From package directory
cd packages/mypackage
auto-version release

# From anywhere, specify config path
auto-version release packages/mypackage/pyproject.toml

# Dry run (see what would happen)
auto-version release --dry-run

# Verbose output
auto-version release --verbose
```

### Status

Check release status without making changes:

```bash
auto-version status
auto-version status packages/mypackage/pyproject.toml
```

## Conventional Commits

Auto-version uses [Conventional Commits](https://www.conventionalcommits.org/) to determine version bumps:

### Format

```
<type>(<scope>): <description>

[optional body]
```

### Examples

```bash
# Minor version bump (0.1.0 → 0.2.0)
git commit -m "feat: add user authentication"

# Patch version bump (0.1.0 → 0.1.1)
git commit -m "fix: correct validation error"

# With scope
git commit -m "feat(api): add new endpoint"

# Multiple types
git commit -m "docs: update README"
git commit -m "perf: optimize query"
```

### Common Types

- `feat`: New feature (minor bump)
- `fix`: Bug fix (patch bump)
- `docs`: Documentation changes (patch bump)
- `perf`: Performance improvements (patch bump)
- `build`: Build system changes (patch bump)
- `ci`: CI configuration changes (patch bump)
- `chore`: Other changes (no bump unless configured)

## Workflow

### 1. Make Changes

```bash
# Edit files
vim mypackage/feature.py

# Commit with conventional commit message
git commit -m "feat: add new feature"
```

### 2. Check Status

```bash
# See what version would be released
auto-version release --dry-run
```

Output:
```
🔍 Dry run mode - no changes will be made

🎉 Release planned for mypackage
  0.1.0 → 0.2.0 (minor bump)
  Tag: mypackage-0.2.0

💡 Run without --dry-run to create the release
   ...or with --push to create and publish it
```

### 3. Create Release

```bash
# Create the release
auto-version release
```

This will:
1. Calculate the new version (0.2.0)
2. Update `pyproject.toml`
3. Update `mypackage/__init__.py`
4. Update `CHANGELOG.md`
5. Create a commit: "release: mypackage 0.2.0"
6. Create a tag: "mypackage-0.2.0"

### 4. Publish

`--push` **replaces** step 3 rather than following it: it creates the release
*and* publishes it. Run it instead of a bare `auto-version release`:

```bash
# Create the release and publish it in one atomic update
auto-version release --push
```

If you have already run step 3, the release exists locally and `--push` will
report "no release needed" — the version comes from tags, and the local tag
already claims it. Publish what you have with git directly; the exact command
is printed by step 3:

```bash
git push --atomic origin HEAD:refs/heads/main refs/tags/mypackage-0.2.0
```

`--push` publishes the commit and tag as a single all-or-nothing ref update, so
the tag can never land without the commit that bumped the version.

If the remote branch moved while the release was being prepared — a concurrent
release job in a monorepo, or an unrelated merge — the push is rejected. Rather
than fail, `--push` **discards the local release and recomputes it** against the
new tip, then pushes again (3 extra attempts by default, jittered):

```bash
auto-version release --push --remote origin --branch main --push-retries 3
```

Recomputing rather than rebasing is deliberate. A rebase would rewrite the
release commit and strand the tag on the orphan, publishing a tag that is not an
ancestor of the branch — and since the version is derived from tags, that
corrupts every later release. Recomputing always yields a commit and tag that
agree with each other and with the branch they are landing on.

Failures that retrying cannot fix (bad credentials, unknown remote) are not
retried.

### Every outcome of `--push`, and what is left where

| Outcome | Exit | Your checkout afterwards | Remote | What to do |
| --- | --- | --- | --- | --- |
| Published | 0 | release commit + tag, on the current tip | commit and tag landed together | nothing |
| Nothing to release | 2 | unchanged | unchanged | nothing |
| Push failed: credentials, hook, unknown remote | 4 | release **kept** — it is valid and based on the current tip | unchanged | fix the cause, then run the `git push --atomic …` command from the error against your original remote (a URL remote's credentials are redacted in the message) |
| Rejected as non-fast-forward, retry succeeded | 0 | release **recomputed** on the new tip | landed | nothing |
| Rejected, retries exhausted | 4 | release **discarded**; back at the commit you started from | unchanged | re-run |
| Branch has commits the remote lacks | 4 | release rolled back; **your commits intact** | unchanged | `git fetch <remote> <branch> && git rebase FETCH_HEAD`, re-run |
| Build command dirtied the tree after the release was created | 3 | release rolled back with `--keep`; **the leaked files intact** | unchanged | fix the build command, declare the files as assets, or ignore them — then re-run |
| Dirty worktree / detached HEAD (pre-flight) | 3 | unchanged — nothing was created | unchanged | commit or stash / pass `--branch` |

Two properties hold on every row. **Only what `--push` created is ever undone**: every
reset is `git reset --keep`, which refuses to overwrite a file with local changes, and a
retry only lands on a tip that contains the commit you started from. **A kept release is
always reported as kept**, because any local release tag makes the next run say "no
release needed".

Ignored files never count as dirty — build output under `.gitignore` neither blocks the
pre-flight check nor a retry.

`--push` refuses to run on a dirty worktree, because retrying resets the
checkout. Untracked files count: `git reset --hard` spares an untracked file
only while its path is absent from the tree being reset onto, so a concurrent
release that adds a file at that path would overwrite it. Ignored files (build
output, virtualenvs) do not count. It also
refuses a detached HEAD unless you pass `--branch`, rather than guessing where
the release should land.

A retry only ever resets onto a tip that already contains the commit publishing
started from, so it can never discard anything `--push` did not create. If your
branch carries commits the remote does not have, the release is rolled back to
where it started and you are asked to rebase — `--push` will not reset your
commits away, and it will not rebase them for you either.

## Changelog Format

Auto-version maintains a CHANGELOG.md in this format:

```markdown
# Changelog

<!--next-version-placeholder-->

## v0.2.0 (2026-02-02)
### Feature
* Add new feature ([`abc123d`](https://github.com/owner/repo/commit/abc123d))

### Fix
* Correct validation error ([`def456e`](https://github.com/owner/repo/commit/def456e))

## v0.1.0 (2026-01-15)
### Feature
* Initial release ([`789abc0`](https://github.com/owner/repo/commit/789abc0))
```

The `<!--next-version-placeholder-->` marker indicates where new releases are inserted.

## Monorepo Usage

For monorepos with multiple packages:

```
monorepo/
├── packages/
│   ├── package-a/
│   │   ├── pyproject.toml  # [tool.auto_version] with tag_format = "package-a-{version}"
│   │   └── package_a/
│   │       └── __init__.py
│   └── package-b/
│       ├── pyproject.toml  # [tool.auto_version] with tag_format = "package-b-{version}"
│       └── package_b/
│           └── __init__.py
```

Release independently:

```bash
# Release package-a
auto-version release packages/package-a/pyproject.toml

# Release package-b
auto-version release packages/package-b/pyproject.toml
```

Each package maintains its own:
- Version numbers
- Git tags (e.g., `package-a-1.0.0`, `package-b-2.0.0`)
- CHANGELOG.md
- Release history

## Path Filters

Control which commits affect a package using `path_filters`:

```toml
[tool.auto_version]
# Only commits touching files in these paths trigger releases
path_filters = [
    "packages/mypackage/",  # All files in package
    "shared/models.py",     # Specific shared file
]
```

## Exit Codes

- `0`: Success
- `1`: Error (configuration, git, etc.)
- `2`: No changes to release
- `3`: Validation error
- `4`: Push rejected — every attempt lost the race, or the push failed for a
  reason retrying cannot fix (bad credentials, unknown remote). Nothing was pushed.

## Testing

Run the test suite:

```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=auto_version --cov-report=html

# Specific test file
pytest tests/test_models.py -v
```

## Troubleshooting

### No release created

If you run `auto-version release` and get "No release needed":

1. Check that you have commits since the last tag:
   ```bash
   git log mypackage-0.1.0..HEAD --oneline
   ```

2. Verify commits are conventional:
   ```bash
   git log --oneline -10
   ```
   Should have formats like `feat:`, `fix:`, etc.

3. Check path filters - commits must touch files in configured paths

### Version not updated

If version isn't updated in files:

1. Check file paths in config are correct (relative to pyproject.toml location)
2. Verify variable format:
   - TOML: `"pyproject.toml:project.version"`
   - Python: `"pkg/__init__.py:__version__"`

### Tag already exists

If you see "Tag already exists":

```bash
# List existing tags
git tag -l 'mypackage-*'

# Delete tag locally
git tag -d mypackage-1.0.0

# Delete tag remotely
git push origin :refs/tags/mypackage-1.0.0
```

## Comparison to python-semantic-release

### Advantages of auto-version

- ✅ **Monorepo native**: Each package has independent versions and tags
- ✅ **Fast**: Analyzes only relevant commits using path filters
- ✅ **Simple**: Focused on versioning, not publishing
- ✅ **Testable**: Full mock git implementation for testing
- ✅ **Transparent**: Clear dry-run mode shows exactly what will happen

### When to use python-semantic-release

- Single repository, single package
- Need PyPI publishing integration
- Need CI/CD integration features
- Want changelog templates beyond conventional format

## Contributing

```bash
# Clone and setup
git clone <repo>
cd auto-version
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Format code
make fix

# Type checking
mypy src/
```
