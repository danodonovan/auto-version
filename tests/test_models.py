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


def test_version_from_string():
    """Test Version.from_string is an alias for parse."""
    v1 = Version.from_string("1.2.3")
    assert v1.major == 1
    assert v1.minor == 2
    assert v1.patch == 3

    v2 = Version.from_string("v4.5.6")
    assert v2.major == 4
    assert v2.minor == 5
    assert v2.patch == 6


# --- PEP 440 pre-release support ---


@pytest.mark.parametrize(
    "version_str,expected",
    [
        ("1.2.3", "1.2.3"),
        ("v1.2.3", "1.2.3"),
        ("1.0.0a1", "1.0.0a1"),
        ("1.0.0b0", "1.0.0b0"),
        ("1.0.0rc2", "1.0.0rc2"),
    ],
)
def test_version_prerelease_round_trip(version_str, expected):
    """Pre-release strings parse and render in normalised PEP 440 form."""
    assert str(Version.parse(version_str)) == expected


def test_version_prerelease_fields():
    """Pre-release segment is stored as a normalised (token, num) tuple."""
    v = Version.parse("1.0.0b1")
    assert (v.major, v.minor, v.patch) == (1, 0, 0)
    assert v.pre == ("b", 1)
    assert v.is_prerelease is True

    final = Version.parse("1.0.0")
    assert final.pre is None
    assert final.is_prerelease is False


def test_version_prerelease_alias_normalisation():
    """Aliases like 'beta'/'c' normalise to PEP 440 tokens."""
    assert str(Version.parse("1.0.0beta1")) == "1.0.0b1"
    assert str(Version.parse("1.0.0-rc.2")) == "1.0.0rc2"
    assert str(Version.parse("1.0.0c3")) == "1.0.0rc3"


def test_version_parse_invalid_prerelease():
    """Genuine garbage still raises ValueError."""
    with pytest.raises(ValueError):
        Version.parse("not-a-version")


def test_version_prerelease_ordering():
    """PEP 440 ordering across pre-releases and finals."""
    versions = [
        Version.parse("1.0.0a1"),
        Version.parse("1.0.0b1"),
        Version.parse("1.0.0b2"),
        Version.parse("1.0.0rc1"),
        Version.parse("1.0.0"),
        Version.parse("1.0.1"),
    ]
    # Already in ascending order; assert each strictly less than the next.
    for lower, higher in zip(versions, versions[1:]):
        assert lower < higher
        assert higher > lower

    # A pre-release ranks above an older final release.
    assert Version.parse("0.11.0") < Version.parse("1.0.0b1")


def test_version_base_version_and_with_prerelease():
    """base_version() drops the pre-release; with_prerelease() applies one."""
    v = Version.parse("1.0.0b2")
    assert v.base_version() == Version(1, 0, 0)
    assert v.base_version().is_prerelease is False

    started = Version(1, 0, 0).with_prerelease("rc", 0)
    assert str(started) == "1.0.0rc0"


def test_version_bump_drops_prerelease():
    """bump() always returns a final version (NONE drops any pre-release)."""
    v = Version.parse("1.0.0b2")
    assert v.bump(VersionBump.PATCH) == Version(1, 0, 1)
    assert v.bump(VersionBump.NONE) == Version(1, 0, 0)
