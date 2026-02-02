"""Parse conventional commit messages."""

import re

from auto_version.models import CommitInfo


# Conventional commit pattern: type(scope): description
CONVENTIONAL_COMMIT_PATTERN = re.compile(
    r"^(?P<type>\w+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?: (?P<description>.+)$"
)


def parse_conventional_commit(commit: CommitInfo) -> CommitInfo:
    """Parse a commit message as a conventional commit.

    Returns a new CommitInfo with commit_type and scope populated.
    If the commit doesn't match conventional format, commit_type will be empty.
    """
    # Try to match the first line of the message
    first_line = commit.message.split("\n")[0].strip()
    match = CONVENTIONAL_COMMIT_PATTERN.match(first_line)

    if not match:
        # Not a conventional commit
        return commit

    commit_type = match.group("type")
    scope = match.group("scope")
    description = match.group("description")
    breaking = match.group("breaking") == "!"

    # Check for BREAKING CHANGE in body
    if "BREAKING CHANGE:" in commit.body or "BREAKING-CHANGE:" in commit.body:
        breaking = True

    # Return updated commit info
    return CommitInfo(
        sha=commit.sha,
        short_sha=commit.short_sha,
        message=commit.message,
        commit_type=commit_type,
        scope=scope,
        description=description,
        body=commit.body,
        timestamp=commit.timestamp,
        affected_files=commit.affected_files,
    )
