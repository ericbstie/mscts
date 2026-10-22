import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from support.leak_guard import kill_survivors
from support.tiers import missing_installations

from mscts import cache
from mscts import group as group_module
from tests.run.fakes import TOKEN_VAR

# pytester runs pytest inside a test; support.console is the plugin it tests (see its docstring).
pytest_plugins = ["pytester", "support.console"]


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


@pytest.fixture
def registering() -> Iterator[None]:
    """Let a test register Groups; forget them afterwards, so no other test sees them."""
    registered = group_module._REGISTERED  # noqa: SLF001 - undo what the test registered
    before = dict(registered)
    yield
    registered.clear()
    registered.update(before)


@pytest.fixture
def run_token() -> Iterator[str]:
    """A token for this test's fake Instances; fails the test if one outlives it."""
    token = uuid.uuid4().hex
    yield token
    leaked = kill_survivors(f"{TOKEN_VAR}={token}")
    assert not leaked, f"fake Instances outlived the test: {leaked}"
