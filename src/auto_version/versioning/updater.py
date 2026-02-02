"""Update version strings in various file formats."""

import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w

from auto_version.models import Version


def update_version_files(
    version_toml: list[str],
    version_variables: list[str],
    new_version: Version,
    package_root: Path,
) -> list[Path]:
    """Update version in all configured files.

    Args:
        version_toml: List of TOML path specs (e.g., ["pyproject.toml:project.version"])
        version_variables: List of Python variable specs (e.g., ["pkg/__init__.py:__version__"])
        new_version: New version to set
        package_root: Root directory of the package

    Returns:
        List of file paths that were modified
    """
    modified_files = []

    # Update TOML files
    for toml_spec in version_toml:
        file_path = _update_toml_version(toml_spec, new_version, package_root)
        modified_files.append(file_path)

    # Update Python variable files
    for var_spec in version_variables:
        file_path = _update_python_version(var_spec, new_version, package_root)
        modified_files.append(file_path)

    return modified_files


def _update_toml_version(spec: str, new_version: Version, package_root: Path) -> Path:
    """Update version in a TOML file.

    Args:
        spec: File spec like "pyproject.toml:project.version"
        new_version: New version to set
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

    # Navigate to the key and update it
    keys = key_path.split(".")
    current = data
    for key in keys[:-1]:
        if key not in current:
            raise KeyError(f"Key path not found in {file_path}: {key_path}")
        current = current[key]

    # Update the final key
    final_key = keys[-1]
    if final_key not in current:
        raise KeyError(f"Key path not found in {file_path}: {key_path}")

    current[final_key] = str(new_version)

    # Write back
    with open(file_path, "wb") as f:
        tomli_w.dump(data, f)

    return file_path


def _update_python_version(spec: str, new_version: Version, package_root: Path) -> Path:
    """Update version in a Python file.

    Args:
        spec: File spec like "package/__init__.py:__version__"
        new_version: New version to set
        package_root: Root directory of the package
    """
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
    pattern = rf'^({re.escape(var_name)}\s*=\s*["\'])([^"\']+)(["\'])'

    def replace_version(match: re.Match[str]) -> str:
        return f"{match.group(1)}{new_version}{match.group(3)}"

    # Replace the version
    new_content, count = re.subn(pattern, replace_version, content, flags=re.MULTILINE)

    if count == 0:
        raise ValueError(
            f"Version variable '{var_name}' not found in {file_path}. "
            f'Expected format: {var_name} = "x.y.z"'
        )

    # Write back
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    return file_path
