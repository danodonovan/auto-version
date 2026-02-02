"""Generate and update changelog files."""

from datetime import datetime
from pathlib import Path

from auto_version.models import CommitInfo, Version


def update_changelog(
    changelog_path: Path,
    new_version: Version,
    commits: list[CommitInfo],
    github_repo: str | None = None,
) -> None:
    """Update CHANGELOG.md with new version information.

    Args:
        changelog_path: Path to CHANGELOG.md
        new_version: Version being released
        commits: List of commits to include
        github_repo: Optional GitHub repo (owner/repo) for commit links
    """
    # Group commits by type
    features = []
    fixes = []
    docs = []
    other = []

    for commit in commits:
        if commit.commit_type == "feat":
            features.append(commit)
        elif commit.commit_type == "fix":
            fixes.append(commit)
        elif commit.commit_type == "docs":
            docs.append(commit)
        elif commit.is_conventional:
            other.append(commit)
        else:
            # Non-conventional commits treated as "other"
            other.append(commit)

    # Build the new version section
    date_str = datetime.now().strftime("%Y-%m-%d")
    lines = [f"## v{new_version} ({date_str})"]

    if features:
        lines.append("### Feature")
        for commit in features:
            lines.append(_format_commit_line(commit, github_repo))

    if fixes:
        lines.append("### Fix")
        for commit in fixes:
            lines.append(_format_commit_line(commit, github_repo))

    if docs:
        lines.append("### Documentation")
        for commit in docs:
            lines.append(_format_commit_line(commit, github_repo))

    if other:
        lines.append("### Other")
        for commit in other:
            lines.append(_format_commit_line(commit, github_repo))

    # Add blank line after section
    lines.append("")

    new_section = "\n".join(lines)

    # Read existing changelog
    if changelog_path.exists():
        with open(changelog_path, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        # Create new changelog
        content = "# Changelog\n\n<!--next-version-placeholder-->\n"

    # Insert new section after the placeholder
    placeholder = "<!--next-version-placeholder-->"
    if placeholder in content:
        # Insert after placeholder
        parts = content.split(placeholder, 1)
        new_content = f"{parts[0]}{placeholder}\n\n{new_section}{parts[1]}"
    else:
        # No placeholder, insert at the beginning after title
        if content.startswith("# Changelog"):
            parts = content.split("\n", 2)
            if len(parts) >= 2:
                new_content = f"{parts[0]}\n{parts[1]}\n\n{new_section}\n{parts[2] if len(parts) > 2 else ''}"
            else:
                new_content = f"{content}\n\n{new_section}"
        else:
            # Add title and content
            new_content = f"# Changelog\n\n{new_section}\n{content}"

    # Write back
    with open(changelog_path, "w", encoding="utf-8") as f:
        f.write(new_content)


def _format_commit_line(commit: CommitInfo, github_repo: str | None) -> str:
    """Format a single commit as a changelog line.

    Format: * Description ([`short_sha`](url))
    """
    description = commit.description or commit.message.split("\n")[0]

    if github_repo:
        commit_url = f"https://github.com/{github_repo}/commit/{commit.sha}"
        return f"* {description} ([`{commit.short_sha}`]({commit_url}))"
    else:
        return f"* {description} ([`{commit.short_sha}`])"
