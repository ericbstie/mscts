from pathlib import Path

import pytest

from mscts import cache


@pytest.fixture(scope="session")
def cache_dir() -> Path:
    """The download cache every worktree and session shares (reference tier only)."""
    return cache.cache_dir()
