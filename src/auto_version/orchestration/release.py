"""Main release orchestration logic."""

from pathlib import Path

from auto_version.analysis.commit_parser import parse_conventional_commit
from auto_version.analysis.version_calculator import calculate_version_bump
from auto_version.changelog.generator import update_changelog
from auto_version.config import Config
from auto_version.git.interface import GitRepository
from auto_version.models import ReleaseResult, Version, VersionBump
from auto_version.versioning.updater import update_version_files


class ReleaseOrchestrator:
    """Orchestrates the full release process."""

    def __init__(self, repo: GitRepository, config: Config) -> None:
        """Initialize the orchestrator.

        Args:
            repo: Git repository interface
            config: Configuration
        """
        self.repo = repo
        self.config = config

    def release(self, dry_run: bool = False) -> ReleaseResult:
        """Execute a full release.

        Args:
            dry_run: If True, don't actually create commits/tags

        Returns:
            Result of the release operation
        """
        # 1. Find the latest release tag
        latest_tag = self._find_latest_tag()

        # 2. Get commits since that tag
        raw_commits = self.repo.get_commits_since(
            latest_tag, path_filters=self.config.path_filters
        )

        # 3. Parse conventional commits
        commits = [parse_conventional_commit(c) for c in raw_commits]

        # 4. Calculate version bump
        bump_type = calculate_version_bump(commits, self.config.commit_parser_options)

        if bump_type == VersionBump.NONE:
            # No release needed
            current_version = self._get_current_version(latest_tag)
            return ReleaseResult(
                package_name=self.config.get_package_name(),
                old_version=current_version,
                new_version=current_version,
                bump_type=bump_type,
                tag="",
                commit_sha="",
                commits_included=commits,
                dry_run=dry_run,
            )

        # 5. Calculate new version
        current_version = self._get_current_version(latest_tag)
        new_version = current_version.bump(bump_type)

        # 6. Check if this version already exists
        new_tag = self.config.format_tag(str(new_version))
        if new_tag in self.repo.get_tags():
            raise ValueError(
                f"Tag {new_tag} already exists. Cannot create release for version {new_version}"
            )

        if dry_run:
            # Stop here for dry run
            return ReleaseResult(
                package_name=self.config.get_package_name(),
                old_version=current_version,
                new_version=new_version,
                bump_type=bump_type,
                tag=new_tag,
                commit_sha="",
                commits_included=commits,
                dry_run=True,
            )

        # 7. Update version files
        modified_files = update_version_files(
            version_toml=self.config.version_toml,
            version_variables=self.config.version_variables,
            new_version=new_version,
            package_root=self.config.package_root,
        )

        # 8. Update changelog
        changelog_path = self.config.package_root / self.config.changelog_path
        update_changelog(
            changelog_path=changelog_path,
            new_version=new_version,
            commits=commits,
            github_repo=self.config.github_repo,
        )
        modified_files.append(changelog_path)

        # 9. Run build command (e.g., to regenerate lock files)
        if self.config.build_command:
            self._run_build_command(self.config.build_command, new_version)

        # 10. Add any additional assets (e.g., lock files)
        for asset in self.config.assets:
            asset_path = self.config.package_root / asset
            if asset_path.exists():
                modified_files.append(asset_path)

        # 11. Create release commit
        self.repo.stage_files(modified_files)
        commit_message = self.config.commit_message.replace(
            "{version}", str(new_version)
        )
        commit_sha = self.repo.create_commit(commit_message, modified_files)

        # 12. Create release tag
        tag_message = f"Release {new_version}"
        self.repo.create_tag(new_tag, tag_message)

        return ReleaseResult(
            package_name=self.config.get_package_name(),
            old_version=current_version,
            new_version=new_version,
            bump_type=bump_type,
            tag=new_tag,
            commit_sha=commit_sha,
            commits_included=commits,
            dry_run=False,
        )

    def _find_latest_tag(self) -> str | None:
        """Find the most recent release tag for this package."""
        # Get all tags matching our format
        package_name = self.config.get_package_name()
        pattern = f"{package_name}-*"
        tags = self.repo.get_tags(pattern)

        if not tags:
            return None

        # Parse versions and find the highest
        versions_with_tags = []
        for tag in tags:
            version_str = self.config.parse_tag_version(tag)
            if version_str:
                try:
                    version = Version.parse(version_str)
                    versions_with_tags.append((version, tag))
                except ValueError:
                    # Skip malformed tags
                    continue

        if not versions_with_tags:
            return None

        # Sort by version and return the tag of the highest version
        versions_with_tags.sort(key=lambda x: x[0], reverse=True)
        return versions_with_tags[0][1]

    def _get_current_version(self, latest_tag: str | None) -> Version:
        """Get the current version from the latest tag."""
        if latest_tag:
            version_str = self.config.parse_tag_version(latest_tag)
            if version_str:
                return Version.parse(version_str)

        # No tag found, default to 0.0.0
        return Version(0, 0, 0)

    def _run_build_command(self, command: str, version: Version) -> None:
        """Run build command after version update.

        Args:
            command: Shell command to run
            version: New version (available for substitution)
        """
        import subprocess

        # Replace {version} placeholder in command
        command = command.replace("{version}", str(version))

        # Run in package root directory
        result = subprocess.run(
            command,
            shell=True,
            cwd=self.config.package_root,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Build command failed: {command}\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )
