from pathlib import Path

import pytest
from support.tiers import missing_installations

from mscts import cache


@pytest.fixture(scope="session")
def cache_dir() -> Path:
    """The download cache every worktree and session shares (reference tier only)."""
    return cache.cache_dir()


def pytest_collection_finish(session: pytest.Session) -> None:
    """Stop before the first test of a live tier whose Installation is missing (ADR-0008).

    Nothing installs it here: the message names the command that would. Under xdist, each
    worker's tests fail on the same message instead (install.require, in their fixtures).
    """
    if hasattr(session.config, "workerinput"):
        return
    markers = {mark.name for item in session.items for mark in item.iter_markers()}
    problems = missing_installations(markers, cache.cache_dir())
    if problems:
        pytest.exit("\n".join(problems), returncode=1)
