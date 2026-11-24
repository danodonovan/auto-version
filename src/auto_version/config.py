"""Configuration loading and validation."""

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


@dataclass
class CommitParserOptions:
    """Options for parsing conventional commits."""

    minor_tags: list[str] = field(default_factory=lambda: ["feat"])
    patch_tags: list[str] = field(
        default_factory=lambda: ["fix", "perf", "docs", "build", "ci"]
    )
    major_tags: list[str] = field(default_factory=list)


@dataclass
class Config:
    """Configuration for auto-version."""

    # Required fields
    tag_format: str
    version_toml: list[str]

    # Optional fields with defaults
    version_variables: list[str] = field(default_factory=list)
    commit_message: str = "release: {version}"
    path_filters: list[str] = field(default_factory=lambda: ["."])
    changelog_path: str = "CHANGELOG.md"
    github_repo: str | None = None
    build_command: str | None = None
    assets: list[str] = field(default_factory=list)
    commit_parser_options: CommitParserOptions = field(
        default_factory=CommitParserOptions
    )

    # Pre-release workflow (both optional; absent => standard X.Y.Z behaviour)
    prerelease_token: str | None = None  # "a" | "b" | "rc"
    release_as: str | None = None  # forces the base release, e.g. "1.0.0"

    # Derived fields (set after loading)
    config_path: Path = field(default=Path())
    package_root: Path = field(default=Path())

    @classmethod
    def from_file(cls, config_path: Path) -> "Config":
        """Load configuration from pyproject.toml."""
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, "rb") as f:
            data = tomllib.load(f)

        if "tool" not in data or "auto_version" not in data["tool"]:
            raise ValueError(
                f"No [tool.auto_version] section found in {config_path}. "
                "Please add configuration to your pyproject.toml."
            )

        av_config = data["tool"]["auto_version"]

        # Required fields
        tag_format = av_config.get("tag_format")
        if not tag_format:
            raise ValueError("tag_format is required in [tool.auto_version]")

        version_toml = av_config.get("version_toml")
        if not version_toml:
            raise ValueError("version_toml is required in [tool.auto_version]")

        # Validate the pre-release channel, if configured.
        prerelease_token = av_config.get("prerelease_token")
        if prerelease_token is not None and prerelease_token not in {"a", "b", "rc"}:
            raise ValueError(
                "prerelease_token must be one of 'a', 'b', 'rc' "
                f"(got {prerelease_token!r})"
            )

        # Parse commit parser options
        parser_opts_data = av_config.get("commit_parser_options", {})
        parser_opts = CommitParserOptions(
            minor_tags=parser_opts_data.get("minor_tags", ["feat"]),
            patch_tags=parser_opts_data.get(
                "patch_tags", ["fix", "perf", "docs", "build", "ci"]
            ),
            major_tags=parser_opts_data.get("major_tags", []),
        )

        # Build config
        config = cls(
            tag_format=tag_format,
            version_toml=version_toml,
            version_variables=av_config.get("version_variables", []),
            commit_message=av_config.get("commit_message", "release: {version}"),
            path_filters=av_config.get("path_filters", ["."]),
            changelog_path=av_config.get("changelog_path", "CHANGELOG.md"),
            github_repo=av_config.get("github_repo"),
            build_command=av_config.get("build_command"),
            assets=av_config.get("assets", []),
            commit_parser_options=parser_opts,
            prerelease_token=prerelease_token,
            release_as=av_config.get("release_as"),
            config_path=config_path.resolve(),
            package_root=config_path.parent.resolve(),
        )

        return config

    def get_package_name(self) -> str:
        """A display name for the package, derived from the tag format.

        The fixed part before the version names the package in a monorepo
        ("mypackage-{version}" -> "mypackage"). A single-package repository
        tags bare versions, and "{version}" has no fixed part — so the package
        directory's name stands in, rather than reporting "Release completed
        for {version}".
        """
        prefix = self.tag_format.split("{version}")[0].rstrip("-_/@. ")
        if prefix:
            return prefix
        return self.package_root.name or self.tag_format

    def format_tag(self, version: str) -> str:
        """Format a tag name from a version."""
        return self.tag_format.replace("{version}", version)

    def parse_tag_version(self, tag: str) -> str | None:
        """Extract version from a tag name, or None if tag doesn't match format."""
        # tag_format is like "mypackage-{version}"
        prefix = self.tag_format.split("{version}")[0]
        suffix = (
            self.tag_format.split("{version}")[-1]
            if "{version}" in self.tag_format
            else ""
        )

        if not tag.startswith(prefix):
            return None
        if suffix and not tag.endswith(suffix):
            return None

        # Extract version part
        version = tag[len(prefix) :]
        if suffix:
            version = version[: -len(suffix)]

        return version
