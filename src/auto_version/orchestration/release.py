"""Main release orchestration logic."""

import random
import time
from pathlib import Path
from typing import Callable

from auto_version.analysis.commit_parser import parse_conventional_commit
from auto_version.analysis.version_calculator import calculate_version_bump
from auto_version.changelog.generator import update_changelog
from auto_version.config import Config
from auto_version.git.interface import (BranchDiverged, GitRepository,
                                        PushRejected, redact_remote)
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
        new_version = self._compute_new_version(current_version, bump_type)

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

    def release_and_publish(
        self,
        remote: str = "origin",
        branch: str | None = None,
        retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> ReleaseResult:
        """Execute a release and publish it, re-deriving it if the push races.

        The release commit and its tag are pushed in one atomic ref update. If
        the remote branch moved under us — another package's release job
        winning the race, or an unrelated merge landing — the local release is
        **discarded and recomputed** against the new tip rather than replayed.

        Replaying is what a rebase would do, and it is wrong here: the tag
        ``release()`` created points at the pre-rebase commit, so rebasing
        strands the tag on an orphan and publishes a tag that is not an
        ancestor of the branch. Since the version is derived from tags, that
        corrupts the input to every later release. Recomputing cannot: each
        attempt produces a commit and tag that agree with each other and with
        the branch they are about to land on.

        What is left on disk depends on why publication failed, because the
        two cases need opposite handling:

        * **Rejected as non-fast-forward, retries exhausted.** The local
          release is not merely unpushed, it is *wrong* — the version it
          claims may have been taken by the release that won, and the bump
          may have changed. It is discarded, so a re-run recomputes cleanly.
        * **Failed for any other reason** (bad credentials, a hook, no such
          remote). The release is correct and based on the current remote tip;
          only publication failed. It is left in place so it can be pushed by
          hand once the cause is fixed.

        The distinction matters because *any* local release tag makes the next
        run report "no release needed" — the version is derived from tags — so
        leaving one behind is only safe when the caller is told it is there.

        A retry only ever resets onto a tip that already contains the commit
        publishing started from, so it cannot discard anything this method did
        not create. If the branch carries commits the remote does not have —
        or the remote was rewritten — the release is rolled back to where it
        started and the caller is asked to rebase, rather than having its
        commits reset away.

        Args:
            remote: Remote to push to
            branch: Branch to push to (default: the current branch)
            retries: Extra attempts after a rejected push (0 disables retrying)
            sleep: Injected for tests; defaults to :func:`time.sleep`

        Returns:
            Result of the release that was published, or a ``NONE`` bump result
            if there was nothing to release.

        Raises:
            ValueError: ``retries`` is negative, HEAD is detached and no
                ``branch`` was given, or the worktree has local modifications.
            BranchDiverged: The remote moved and this branch carries
                commits it does not contain; the release was rolled back.
            PushRejected: The push failed for a reason retrying cannot fix, or
                every attempt was rejected.
        """
        shown_remote = redact_remote(remote)

        if retries < 0:
            raise ValueError(f"retries must be zero or greater, got {retries}")

        if branch is None:
            branch = self.repo.get_current_branch()
            if branch is None:
                raise ValueError(
                    "HEAD is detached, so there is no branch to publish to. "
                    "Pass an explicit branch (--branch) to say where this "
                    "release should land."
                )

        # A retry resets the worktree, which would discard local modifications
        # along with the release being retried. Checked before the first
        # release() call, since release() dirties the tree itself.
        if self.repo.is_dirty():
            raise ValueError(
                "the worktree has local modifications, which publishing may "
                "discard when retrying a rejected push. Commit or stash them "
                "first."
            )

        # The commit publishing starts from. A retry may only reset onto a tip
        # that already contains it, so the reset can never discard more than
        # this method created.
        try:
            base_sha = self.repo.resolve("HEAD")
        except Exception:
            # Unborn repository: no commits, so there is nothing to release
            # and nothing to roll back to. Let release() report that the
            # normal way instead of surfacing a rev-parse failure. (Usually
            # the dirty-worktree check catches this first, since an unborn
            # repo's files are untracked — but not if they are ignored.)
            return self.release(dry_run=False)

        attempt = 0
        while True:
            result = self.release(dry_run=False)

            if result.bump_type == VersionBump.NONE:
                return result

            try:
                self.repo.push(
                    remote,
                    [f"HEAD:refs/heads/{branch}", f"refs/tags/{result.tag}"],
                )
            except PushRejected as exc:
                if not exc.non_fast_forward:
                    # Correct release, external failure: leave it to be pushed
                    # by hand. The caller reports the tag and the command.
                    raise
                # Drop the tag before resetting so it cannot survive pointing
                # at a commit that is about to stop existing. If the deletion
                # genuinely fails this raises, and the reset below is skipped
                # rather than orphaning the tag.
                self.repo.delete_tag(result.tag)
                # Reset to the ref fetch() names, not to a composed
                # "<remote>/<branch>": the remote-tracking ref is only
                # updated opportunistically, so composing it risks resetting
                # to the tip we just lost the race to and repeating the same
                # rejected push until the retries run out.
                try:
                    fetched = self.repo.fetch(remote, branch)
                except Exception:
                    # The tag is already gone, so failing here would strand an
                    # untagged release commit at HEAD — which a later run
                    # cannot tell from unreleased work, and would release
                    # again on top of, duplicating the commit and its
                    # changelog entry. Put the branch back instead.
                    self.repo.reset_hard(base_sha)
                    raise

                if not self.repo.is_ancestor(base_sha, fetched):
                    # The branch carries commits the remote does not have, or
                    # the remote was rewritten. Resetting onto the fetched tip
                    # would discard work this method did not create, so put
                    # the release back where it started and stop.
                    self.repo.reset_hard(base_sha)
                    # Describe the target as "<branch> on <remote>" rather
                    # than composing "<remote>/<branch>": remote may be a URL,
                    # which would render as a ref nobody can rebase onto.
                    raise BranchDiverged(
                        f"{branch} on {shown_remote} has moved, and this "
                        f"branch has "
                        f"commits that are not on it, so the release cannot "
                        f"be recomputed without discarding them. The release "
                        f"was rolled back to {base_sha[:7]} and nothing was "
                        f"published. Rebase onto the fetched {branch} "
                        f"(git fetch {shown_remote} {branch} && git rebase "
                        f"FETCH_HEAD) and re-run."
                        f"\n\nUnderlying push failure:\n{exc}",
                        non_fast_forward=True,
                    ) from exc

                if self.repo.is_dirty():
                    # release() commits what it creates, so anything left here
                    # came from the configured build command writing outside
                    # its declared assets. The reset below would destroy it,
                    # and the pre-flight check ran before that command existed
                    # to produce it.
                    self.repo.reset_hard(base_sha)
                    raise ValueError(
                        "the build command left files in the worktree that are "
                        "not part of the release, and retrying would discard "
                        f"them. The release was rolled back to {base_sha[:7]} "
                        "and nothing was published. Add them to the release's "
                        "assets, ignore them, or have the build command clean "
                        "up after itself."
                    )

                self.repo.reset_hard(fetched)
                # This attempt's starting point, and the only state we promise
                # to restore, is now the tip we just landed on. Leaving it at
                # the original HEAD would let a later attempt accept a fetched
                # tip that dropped what this one accepted — exactly the
                # rewritten-history case the containment check exists to catch.
                base_sha = self.repo.resolve("HEAD")
                if attempt >= retries:
                    raise
                attempt += 1
                sleep(self._backoff(attempt - 1))
                continue

            return result

    @staticmethod
    def _backoff(attempt: int) -> float:
        """Jittered backoff so racing jobs do not retry in lockstep."""
        return random.uniform(0.0, min(2.0**attempt, 8.0))

    def get_latest_version(self) -> Version | None:
        """Return the latest released version (PEP 440 ordered), or None if untagged.

        Unlike reading ``get_tags()[0]`` directly, this honours PEP 440 ordering
        so pre-releases are ranked correctly (e.g. 1.0.0b1 over 0.11.0, and below 1.0.0).
        """
        latest_tag = self._find_latest_tag()
        if latest_tag is None:
            return None
        version_str = self.config.parse_tag_version(latest_tag)
        if not version_str:
            return None
        return Version.parse(version_str)

    def _find_latest_tag(self) -> str | None:
        """Find the most recent release tag for this package."""
        # Get all tags matching our format by converting tag_format to glob pattern
        # e.g., "kg-{version}" -> "kg-*", "v{version}" -> "v*", "pkg/v{version}-release" -> "pkg/v*-release"
        pattern = self.config.tag_format.replace("{version}", "*")
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

    def _compute_new_version(self, base: Version, bump_type: VersionBump) -> Version:
        """Compute the next version, honouring the pre-release workflow config.

        Four cases (see the pre-release spec):
          1. Start a line   — token set, and base is final (or release_as forces it).
          2. Iterate a line — token set, base is a pre-release on the same token.
          3. Channel change — token set, base is a pre-release on a different token.
          4. Graduate       — token unset, base is a pre-release: drop the pre-release.
          5. Normal         — token unset, base is final: standard bump (unchanged).
        """
        token = self.config.prerelease_token

        if token is None:
            if base.is_prerelease:
                # Graduate: 1.0.0b2 -> 1.0.0
                return base.base_version()
            # Normal: standard X.Y.Z bump
            return base.bump(bump_type)

        # A pre-release channel is active.
        if base.is_prerelease and not self.config.release_as:
            # Iterate (same token) or channel change (different token); in both
            # cases the base release is fixed and the number comes from existing tags.
            target = base.base_version()
        elif self.config.release_as:
            # Start a line at an explicitly forced base.
            target = Version.parse(self.config.release_as)
        else:
            # Start a line from a commit-derived bump of a final base.
            target = base.bump(bump_type)

        number = self._next_prerelease_number(target, token)
        return target.with_prerelease(token, number)

    def _next_prerelease_number(self, target: Version, token: str) -> int:
        """Next pre-release number for ``target``+``token``, scanning existing tags.

        Returns ``max(existing numbers) + 1`` so a re-run after a partial release
        continues the sequence (e.g. picks ``b3`` when ``b1``/``b2`` exist) rather
        than colliding, or ``0`` when the line has no tags yet.
        """
        pattern = self.config.tag_format.replace("{version}", "*")
        target_base = target.base_version()

        numbers = []
        for tag in self.repo.get_tags(pattern):
            version_str = self.config.parse_tag_version(tag)
            if not version_str:
                continue
            try:
                version = Version.parse(version_str)
            except ValueError:
                continue
            if (
                version.pre is not None
                and version.pre[0] == token
                and version.base_version() == target_base
            ):
                numbers.append(version.pre[1])

        return max(numbers) + 1 if numbers else 0

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
