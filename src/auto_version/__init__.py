"""Auto-version: Automatic release management for Python monorepos."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _metadata_version

try:
    __version__ = _metadata_version("auto-version")
except PackageNotFoundError:  # running from a source tree, not installed
    __version__ = "0.0.0+unknown"

from auto_version.config import Config
from auto_version.orchestration.release import ReleaseOrchestrator

__all__ = ["Config", "ReleaseOrchestrator", "__version__"]
