"""Two Reference Instances for the whole Self-check tier, and how many times to play each Group.

Booting vanilla takes ~10 s (docs/research/2026-09-26-runner.md), so the tier boots its two
Instances once, together, and every Group's Self-check plays against that pair. A Group
whose Self-check changes the world leaves it so for the Groups after it: a Group that needs
a clean world sets it up itself (a Control command), as it must for the Candidate too.
"""

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from support.reference import booted
from support.selfcheck import (
    pytest_generate_tests,  # noqa: F401 - one test per registered Group
    repeat_from,
)

from mscts.runner import Instance


@pytest.fixture(scope="session")
def repeat() -> int:
    """How many times each Group is played: `MSCTS_SELFCHECK_REPEAT`, else 3."""
    return repeat_from(os.environ)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def references(
    cache_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> AsyncIterator[tuple[Instance, Instance]]:
    """The tier's two Reference Instances, at the default ServerSpec, booted together."""
    async with contextlib.AsyncExitStack() as stack:
        async with asyncio.TaskGroup() as boots:
            first, second = (
                boots.create_task(
                    stack.enter_async_context(booted(cache_dir, tmp_path_factory.mktemp(name)))
                )
                for name in ("reference", "second-reference")
            )
        yield first.result(), second.result()


@pytest.fixture(scope="session")
def reference(references: tuple[Instance, Instance]) -> Instance:
    """The first Instance of the pair: the side a Candidate would be compared against."""
    return references[0]


@pytest.fixture(scope="session")
def second_reference(references: tuple[Instance, Instance]) -> Instance:
    """The second Instance of the pair: the stand-in for a Candidate."""
    return references[1]
