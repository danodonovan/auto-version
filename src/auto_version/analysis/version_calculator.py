"""Calculate version bumps from conventional commits."""

from auto_version.config import CommitParserOptions
from auto_version.models import CommitInfo, VersionBump


def calculate_version_bump(
    commits: list[CommitInfo], options: CommitParserOptions
) -> VersionBump:
    """Calculate the appropriate version bump for a list of commits.

    Args:
        commits: List of parsed conventional commits
        options: Parser options defining which commit types trigger which bumps

    Returns:
        The highest level bump required (major > minor > patch > none)
    """
    if not commits:
        return VersionBump.NONE

    has_major = False
    has_minor = False
    has_patch = False

    for commit in commits:
        if not commit.is_conventional:
            # Non-conventional commits are treated as patch-level changes
            has_patch = True
            continue

        # Breaking changes always trigger a major bump
        if commit.breaking:
            has_major = True
            continue

        commit_type = commit.commit_type

        if commit_type in options.major_tags:
            has_major = True
        elif commit_type in options.minor_tags:
            has_minor = True
        elif commit_type in options.patch_tags:
            has_patch = True

    # Return highest level bump
    if has_major:
        return VersionBump.MAJOR
    elif has_minor:
        return VersionBump.MINOR
    elif has_patch:
        return VersionBump.PATCH
    else:
        return VersionBump.NONE
