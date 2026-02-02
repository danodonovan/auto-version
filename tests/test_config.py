"""Tests for configuration loading."""

from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from auto_version.config import Config


def test_config_from_file():
    """Test loading configuration from a file."""
    config_content = """
[tool.auto_version]
tag_format = "mypackage-{version}"
version_toml = ["pyproject.toml:project.version"]
version_variables = ["mypackage/__init__.py:__version__"]
commit_message = "release: {version}"
path_filters = ["."]
github_repo = "owner/repo"

[tool.auto_version.commit_parser_options]
minor_tags = ["feat"]
patch_tags = ["fix", "docs"]
"""

    with NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(config_content)
        f.flush()
        config_path = Path(f.name)

    try:
        config = Config.from_file(config_path)

        assert config.tag_format == "mypackage-{version}"
        assert config.version_toml == ["pyproject.toml:project.version"]
        assert config.version_variables == ["mypackage/__init__.py:__version__"]
        assert config.commit_message == "release: {version}"
        assert config.path_filters == ["."]
        assert config.github_repo == "owner/repo"
        assert config.commit_parser_options.minor_tags == ["feat"]
        assert config.commit_parser_options.patch_tags == ["fix", "docs"]
    finally:
        config_path.unlink()


def test_config_get_package_name():
    """Test extracting package name from tag format."""
    config_content = """
[tool.auto_version]
tag_format = "mypackage-{version}"
version_toml = ["pyproject.toml:project.version"]
"""

    with NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(config_content)
        f.flush()
        config_path = Path(f.name)

    try:
        config = Config.from_file(config_path)
        assert config.get_package_name() == "mypackage"
    finally:
        config_path.unlink()


def test_config_format_tag():
    """Test formatting a tag name."""
    config_content = """
[tool.auto_version]
tag_format = "mypackage-{version}"
version_toml = ["pyproject.toml:project.version"]
"""

    with NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(config_content)
        f.flush()
        config_path = Path(f.name)

    try:
        config = Config.from_file(config_path)
        assert config.format_tag("1.2.3") == "mypackage-1.2.3"
    finally:
        config_path.unlink()


def test_config_parse_tag_version():
    """Test parsing version from a tag name."""
    config_content = """
[tool.auto_version]
tag_format = "mypackage-{version}"
version_toml = ["pyproject.toml:project.version"]
"""

    with NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(config_content)
        f.flush()
        config_path = Path(f.name)

    try:
        config = Config.from_file(config_path)
        assert config.parse_tag_version("mypackage-1.2.3") == "1.2.3"
        assert config.parse_tag_version("otherpackage-1.2.3") is None
    finally:
        config_path.unlink()


def test_config_missing_required_fields():
    """Test that missing required fields raise errors."""
    config_content = """
[tool.auto_version]
# Missing required fields
"""

    with NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(config_content)
        f.flush()
        config_path = Path(f.name)

    try:
        with pytest.raises(ValueError, match="tag_format is required"):
            Config.from_file(config_path)
    finally:
        config_path.unlink()
