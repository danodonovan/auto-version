"""Auto-version: Automatic release management for Python monorepos."""

__version__ = "0.1.0"

from auto_version.config import Config
from auto_version.orchestration.release import ReleaseOrchestrator

__all__ = ["Config", "ReleaseOrchestrator", "__version__"]
