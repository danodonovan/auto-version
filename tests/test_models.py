"""Tests for core models."""

import pytest

from auto_version.models import Version, VersionBump


def test_version_parse():
    """Test version parsing."""
    v = Version.parse("1.2.3")
    assert v.major == 1
    assert v.minor == 2
    assert v.patch == 3


def test_version_parse_with_v_prefix():
    """Test parsing version with 'v' prefix."""
    v = Version.parse("v2.3.4")
    assert v.major == 2
    assert v.minor == 3
    assert v.patch == 4


def test_version_parse_invalid():
    """Test parsing invalid version."""
    with pytest.raises(ValueError):
        Version.parse("invalid")


def test_version_str():
    """Test version string representation."""
    v = Version(1, 2, 3)
    assert str(v) == "1.2.3"


def test_version_bump_major():
    """Test major version bump."""
    v = Version(1, 2, 3)
    new_v = v.bump(VersionBump.MAJOR)
    assert new_v == Version(2, 0, 0)


def test_version_bump_minor():
    """Test minor version bump."""
    v = Version(1, 2, 3)
    new_v = v.bump(VersionBump.MINOR)
    assert new_v == Version(1, 3, 0)


def test_version_bump_patch():
    """Test patch version bump."""
    v = Version(1, 2, 3)
    new_v = v.bump(VersionBump.PATCH)
    assert new_v == Version(1, 2, 4)


def test_version_bump_none():
    """Test no version bump."""
    v = Version(1, 2, 3)
    new_v = v.bump(VersionBump.NONE)
    assert new_v == v


def test_version_comparison():
    """Test version comparison."""
    v1 = Version(1, 2, 3)
    v2 = Version(1, 2, 4)
    v3 = Version(2, 0, 0)

    assert v1 < v2
    assert v2 < v3
    assert v1 <= v2
    assert v2 > v1
    assert v3 >= v2
