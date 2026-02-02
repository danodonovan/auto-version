"""Read version strings from various file formats."""

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from auto_version.config import Config
from auto_version.models import Version


def read_version(config: Config) -> Version:
    """Read the current version from config files.

    Reads from the first available source in this order:
    1. version_toml entries
    2. version_variables entries

    Args:
        config: Configuration containing version file specifications

    Returns:
        Current version found in the config files

    Raises:
        FileNotFoundError: If no version files are found
        ValueError: If version cannot be parsed
    """
    # Try TOML files first
    if config.version_toml:
        spec = config.version_toml[0]
        return _read_toml_version(spec, config.package_root)

    # Try Python variable files
    if config.version_variables:
        spec = config.version_variables[0]
        return _read_python_version(spec, config.package_root)

    raise ValueError("No version files configured")


def _read_toml_version(spec: str, package_root: Path) -> Version:
    """Read version from a TOML file.

    Args:
        spec: File spec like "pyproject.toml:project.version"
        package_root: Root directory of the package
    """
    parts = spec.split(":")
    if len(parts) != 2:
        raise ValueError(
            f"Invalid TOML spec: {spec}. Expected format: 'file.toml:key.path'"
        )

    file_name, key_path = parts
    file_path = package_root / file_name

    if not file_path.exists():
        raise FileNotFoundError(f"TOML file not found: {file_path}")

    # Load TOML
    with open(file_path, "rb") as f:
        data = tomllib.load(f)

    # Navigate to the key
    keys = key_path.split(".")
    current = data
    for key in keys:
        if key not in current:
            raise KeyError(f"Key path not found in {file_path}: {key_path}")
        current = current[key]

    # Parse version string
    version_str = str(current)
    return Version.from_string(version_str)


def _read_python_version(spec: str, package_root: Path) -> Version:
    """Read version from a Python file.

    Args:
        spec: File spec like "package/__init__.py:__version__"
        package_root: Root directory of the package
    """
    import re

    parts = spec.split(":")
    if len(parts) != 2:
        raise ValueError(
            f"Invalid Python spec: {spec}. Expected format: 'file.py:variable_name'"
        )

    file_name, var_name = parts
    file_path = package_root / file_name

    if not file_path.exists():
        raise FileNotFoundError(f"Python file not found: {file_path}")

    # Read file content
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Pattern to match the version variable
    # Matches: __version__ = "1.2.3" or __version__ = '1.2.3'
    pattern = rf'^{re.escape(var_name)}\s*=\s*["\']([^"\']+)["\']'

    match = re.search(pattern, content, flags=re.MULTILINE)
    if not match:
        raise ValueError(
            f"Version variable '{var_name}' not found in {file_path}. "
            f'Expected format: {var_name} = "x.y.z"'
        )

    version_str = match.group(1)
    return Version.from_string(version_str)
