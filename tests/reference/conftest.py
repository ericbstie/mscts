"""One shared, stateless vanilla Reference Instance for the whole reference-tier session.

Booting vanilla takes ~10 s (docs/research/2026-09-26-runner.md), so tests that only
need a plain, unmodified Reference (no Fixture, nothing that could leave state another
test would see; a join only by a Bot with a name no other test uses) share one Instance
instead of each booting their own.
A test that needs a *different* ServerSpec, or that changes world or player state,
boots its own Instance instead, with `boot_reference`.
"""

import contextlib
import functools
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
import pytest_asyncio
from support.reference import attached, booted

from mscts.run import Attached
from mscts.runner import Instance

type BootReference = Callable[..., contextlib.AbstractAsyncContextManager[Instance]]
"""`boot_reference(**changes)`: a Reference of the test's own, at the default ServerSpec
with `changes` (ServerSpec fields), for `async with`."""


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def reference(
    cache_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> AsyncIterator[Instance]:
    """The session's one Reference Instance, at the default ServerSpec."""
    async with booted(cache_dir, tmp_path_factory.mktemp("reference")) as instance:
        yield instance


@pytest.fixture
def boot_reference(cache_dir: Path, tmp_path: Path) -> BootReference:
    """Boot a Reference of the test's own, with ServerSpec changes such as view_distance=4."""
    return functools.partial(booted, cache_dir, tmp_path / "reference")


@pytest.fixture(scope="session")
def reference_attached(reference: Instance) -> Attached:
    """The session's Reference Instance as a Run's Attached side (the fixture owns it)."""
    return attached(reference)
