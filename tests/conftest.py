from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def cache_dir() -> Path:
    """The repo's git-ignored download cache, shared across runs (reference tier only)."""
    return Path(__file__).resolve().parents[1] / ".cache" / "mscts"
