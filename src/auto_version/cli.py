"""Command-line interface for auto-version."""

import sys
from pathlib import Path

import click

from auto_version.config import Config
from auto_version.git.interface import BranchDiverged, PushRejected, redact_remote
from auto_version.git.pygit2_impl import PyGit2Repository
from auto_version.models import VersionBump
from auto_version.orchestration.release import ReleaseOrchestrator


@click.group()
@click.version_option()
def main() -> None:
    """Auto-version: Automatic release management for Python monorepos."""
    pass


@main.command()
@click.argument(
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    required=False,
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be done without actually doing it",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed output",
)
@click.option(
    "--push/--no-push",
    default=False,
    help="Push the release commit and tag atomically, retrying if the "
    "remote branch moved (recomputing the version each time)",
)
@click.option(
    "--remote",
    default="origin",
    show_default=True,
    help="Remote to push to (with --push)",
)
@click.option(
    "--branch",
    default=None,
    help="Branch to push to (with --push; default: the current branch)",
)
@click.option(
    "--push-retries",
    # Plain int, not IntRange: a Click usage error exits 2, which this tool
    # documents as "no release needed". release_and_publish rejects a
    # negative count with ValueError, which exits 3 like other bad input.
    type=int,
    default=3,
    show_default=True,
    help="Extra attempts after a rejected push (0 disables retrying)",
)
def release(
    config_path: Path | None,
    dry_run: bool,
    verbose: bool,
    push: bool,
    remote: str,
    branch: str | None,
    push_retries: int,
) -> None:
    """Create a new release for a package.

    CONFIG_PATH: Path to pyproject.toml (optional, defaults to ./pyproject.toml)

    Examples:

        \b
        # Release from current directory
        auto-version release

        \b
        # Release a specific package
        auto-version release packages/mypackage/pyproject.toml

        \b
        # Dry run to see what would happen
        auto-version release --dry-run

        \b
        # Release and publish it, tolerating concurrent release jobs
        auto-version release --push
    """
    if push and dry_run:
        click.echo(
            "Error: --push cannot be combined with --dry-run "
            "(a dry run creates nothing to push).",
            err=True,
        )
        sys.exit(3)

    # Shown wherever the remote appears in output: a URL remote may carry
    # a token, and these lines reach CI logs.
    shown_remote = redact_remote(remote)

    try:
        # Find config file
        if config_path is None:
            config_path = Path.cwd() / "pyproject.toml"
            if not config_path.exists():
                click.echo(
                    "Error: No pyproject.toml found in current directory. "
                    "Please specify a path or run from a package directory.",
                    err=True,
                )
                sys.exit(1)

        # Load configuration
        if verbose:
            click.echo(f"Loading configuration from {config_path}")

        config = Config.from_file(config_path)

        # Initialize git repository
        if verbose:
            click.echo(f"Initializing git repository from {config.package_root}")

        repo = PyGit2Repository(config.package_root)

        # Create orchestrator and run release
        orchestrator = ReleaseOrchestrator(repo, config)

        if dry_run:
            click.echo("🔍 Dry run mode - no changes will be made\n")

        if verbose:
            click.echo("Analyzing commits and calculating version bump...")

        if push:
            result = orchestrator.release_and_publish(
                remote=remote, branch=branch, retries=push_retries
            )
        else:
            result = orchestrator.release(dry_run=dry_run)

        # Display results
        if result.bump_type == VersionBump.NONE:
            click.echo(f"✓ No release needed for {result.package_name}")
            click.echo(f"  Current version: {result.old_version}")
            click.echo(f"  No releasable commits found since last release")
            if verbose and result.commits_included:
                click.echo(f"\n  Commits analyzed: {len(result.commits_included)}")
                for commit in result.commits_included:
                    click.echo(f"    - {commit.short_sha}: {commit.description}")
            sys.exit(2)  # Exit code 2 = no changes

        click.echo(
            f"🎉 Release {'planned' if dry_run else 'completed'} for {result.package_name}"
        )
        click.echo(
            f"  {result.old_version} → {result.new_version} ({result.bump_type.value} bump)"
        )
        click.echo(f"  Tag: {result.tag}")

        if not dry_run:
            click.echo(f"  Commit: {result.commit_sha[:7]}")

        if result.leaked_paths:
            # Only reachable without --push: publishing rolls the release back
            # and raises instead. A warning rather than an error here, because
            # erroring would change what plain `release` has always done — but
            # silence would let the same build command pass today and fail the
            # moment someone adds --push.
            click.echo(
                "\n⚠️  The build command wrote files the release does not " "include:",
                err=True,
            )
            click.echo(
                orchestrator.format_leaked_paths(result.leaked_paths, "     "), err=True
            )
            click.echo(
                "   They are left in the worktree, uncommitted. Declare them "
                "as release\n   assets, ignore them, or have the build command "
                "clean up after itself —\n   --push refuses to publish while "
                "they are present.",
                err=True,
            )
            suggestion = orchestrator.assets_suggestion(result.leaked_paths)
            if suggestion:
                click.echo(
                    "\n   If they belong in the release, declare them under "
                    f"[tool.auto_version]:\n       {suggestion}",
                    err=True,
                )

        if verbose:
            click.echo(f"\n  Commits included ({len(result.commits_included)}):")
            for commit in result.commits_included:
                commit_type = commit.commit_type or "other"
                click.echo(
                    f"    [{commit_type}] {commit.short_sha}: {commit.description}"
                )

            if dry_run:
                # Show what would be changed
                click.echo("\n  📝 Changes that would be made:")

                # Show version file updates
                click.echo(f"\n  Version files:")
                for spec in config.version_toml:
                    click.echo(f"    {spec}")
                    click.echo(f"      {result.old_version} → {result.new_version}")

                for spec in config.version_variables:
                    click.echo(f"    {spec}")
                    click.echo(f"      {result.old_version} → {result.new_version}")

                # Show changelog
                click.echo(f"\n  Changelog ({config.changelog_path}):")
                click.echo(f"    New section: v{result.new_version}")

                # Group commits by type for preview
                from collections import defaultdict

                commits_by_type = defaultdict(list)
                for commit in result.commits_included:
                    if commit.commit_type == "feat":
                        commits_by_type["Feature"].append(commit)
                    elif commit.commit_type == "fix":
                        commits_by_type["Fix"].append(commit)
                    elif commit.commit_type == "docs":
                        commits_by_type["Documentation"].append(commit)
                    else:
                        commits_by_type["Other"].append(commit)

                for section, commits in sorted(commits_by_type.items()):
                    click.echo(f"    ### {section}")
                    for commit in commits[:3]:  # Show first 3
                        click.echo(
                            f"    * {commit.description} ([`{commit.short_sha}`])"
                        )
                    if len(commits) > 3:
                        click.echo(f"    ... and {len(commits) - 3} more")

                # Show build command if configured
                if config.build_command:
                    build_cmd = config.build_command.replace(
                        "{version}", str(result.new_version)
                    )
                    click.echo(f"\n  Build command:")
                    click.echo(f"    {build_cmd}")
                    if config.assets:
                        click.echo(f"    Additional assets: {', '.join(config.assets)}")

                # Show commit and tag
                commit_msg = config.commit_message.replace(
                    "{version}", str(result.new_version)
                )
                total_files = (
                    len(config.version_toml)
                    + len(config.version_variables)
                    + 1
                    + len(config.assets)
                )
                click.echo(f"\n  Git commit:")
                click.echo(f"    Message: {commit_msg}")
                click.echo(f"    Files: {total_files} files")

                click.echo(f"\n  Git tag:")
                click.echo(f"    Name: {result.tag}")
                click.echo(f"    Message: Release {result.new_version}")

        if dry_run:
            click.echo("\n💡 Run without --dry-run to create the release")
            click.echo("   ...or with --push to create and publish it")
        elif push:
            click.echo(f"\n✅ Pushed to {shown_remote} ({result.tag})")
        else:
            # Name the branch rather than shelling out to
            # `git branch --show-current`, which is empty on a detached HEAD
            # and would print an invalid refspec (HEAD:refs/heads/).
            target = repo.get_current_branch()
            click.echo("\n💡 Push the release:")
            if target is None:
                click.echo(
                    f"   git push --atomic {shown_remote} "
                    f"HEAD:refs/heads/<branch> refs/tags/{result.tag}"
                )
                click.echo(
                    "   HEAD is detached, so substitute the branch this "
                    "release belongs on."
                )
            else:
                click.echo(
                    f"   git push --atomic {shown_remote} "
                    f"HEAD:refs/heads/{target} refs/tags/{result.tag}"
                )
            click.echo(
                "   (--push creates and publishes in one step; it cannot\n"
                "    publish a release that already exists locally)"
            )

    except BranchDiverged as e:
        # Message is complete on its own: re-running will not help until
        # the branch is rebased, so the generic advice below must not run.
        click.echo(f"Error: {e}", err=True)
        sys.exit(4)
    except PushRejected as e:
        click.echo(f"Error: {e}", err=True)
        if e.non_fast_forward:
            click.echo(
                f"\nEvery attempt was rejected: {shown_remote} is moving faster "
                "than the retries. Nothing was published, and the local "
                "release was discarded — re-run to recompute it.",
                err=True,
            )
        else:
            click.echo(
                "\nThe release was created locally but not published. It is "
                "correct — only the push failed — so it has been left in "
                "place. Fix the cause above, then re-run the git push shown in "
                "the error against your original remote — any credentials in "
                "a URL remote are redacted in that message, so it is not "
                "runnable exactly as shown.\n"
                "Until then this package will report 'no release needed', "
                "because the local tag already claims that version.",
                err=True,
            )
        sys.exit(4)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(3)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        if verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


@main.command()
@click.argument(
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    required=False,
)
def status(config_path: Path | None) -> None:
    """Show the current release status for a package.

    CONFIG_PATH: Path to pyproject.toml (optional, defaults to ./pyproject.toml)
    """
    try:
        # Find config file
        if config_path is None:
            config_path = Path.cwd() / "pyproject.toml"

        if not config_path.exists():
            click.echo("Error: No pyproject.toml found", err=True)
            sys.exit(1)

        # Load configuration
        config = Config.from_file(config_path)
        repo = PyGit2Repository(config.package_root)

        # Create orchestrator
        orchestrator = ReleaseOrchestrator(repo, config)

        # Do a dry run to get status
        result = orchestrator.release(dry_run=True)

        click.echo(f"Package: {result.package_name}")
        click.echo(f"Current version: {result.old_version}")

        if result.bump_type == VersionBump.NONE:
            click.echo("Status: ✓ Up to date (no unreleased changes)")
        else:
            click.echo(f"Status: ⚠ Unreleased changes detected")
            click.echo(
                f"Next version: {result.new_version} ({result.bump_type.value} bump)"
            )
            click.echo(f"Commits: {len(result.commits_included)}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument(
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    required=False,
)
def show_version(config_path: Path | None) -> None:
    """Show the current version for a package.

    CONFIG_PATH: Path to pyproject.toml (optional, defaults to ./pyproject.toml)

    This command outputs only the version number (e.g., "1.2.3") to stdout,
    making it suitable for use in scripts and CI/CD pipelines.

    Examples:

        \b
        # Get current version
        auto-version show-version

        \b
        # Get version for specific package
        auto-version show-version packages/mypackage/pyproject.toml

        \b
        # Use in shell script
        VERSION=$(auto-version show-version)
    """
    try:
        # Find config file
        if config_path is None:
            config_path = Path.cwd() / "pyproject.toml"

        if not config_path.exists():
            click.echo("Error: No pyproject.toml found", err=True)
            sys.exit(1)

        # Load configuration
        config = Config.from_file(config_path)
        repo = PyGit2Repository(config.package_root)

        # Find the latest released version using PEP 440 ordering, so pre-releases
        # (e.g. 1.0.0b1) rank correctly rather than tying with the final release.
        orchestrator = ReleaseOrchestrator(repo, config)
        version = orchestrator.get_latest_version()

        if version is not None:
            click.echo(str(version))
        else:
            # No tag found, get version from config files
            from auto_version.versioning.reader import read_version

            version = read_version(config)
            click.echo(str(version))

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
