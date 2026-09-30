"""One shared, stateless vanilla Reference Instance for the whole reference-tier session.

Booting vanilla takes ~10 s (docs/research/2026-09-26-runner.md), so tests that only
need a plain, unmodified Reference (no Fixture, nothing that could leave state another
test would see; a join only by a Bot with a name no other test uses) share one Instance
instead of each booting their own.
A test that needs a *different* ServerSpec, or that changes world or player state,
boots its own Instance instead, with `boot_reference`.
"""

import contextlib
import dataclasses
import functools
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
import pytest_asyncio
from support.leak_guard import kill_survivors

from mscts import install
from mscts.adapters.vanilla import VanillaAdapter
from mscts.bot import status_probe
from mscts.net import Endpoint
from mscts.run import Attached
from mscts.runner import Instance, free_endpoint, running
from mscts.spec import ServerSpec
from mscts.target import TARGET

READY_TIMEOUT_S = 120  # a cold first boot unpacks the bundled libraries and makes a world
STOP_TIMEOUT_S = 30
_TOKEN_VAR = "MSCTS_REFERENCE_TOKEN"  # noqa: S105 - an env var name, not a secret

type BootReference = Callable[..., contextlib.AbstractAsyncContextManager[Instance]]
"""`boot_reference(**changes)`: a Reference of the test's own, at the default ServerSpec
with `changes` (ServerSpec fields), for `async with`."""


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def reference(
    cache_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> AsyncIterator[Instance]:
    """The session's one Reference Instance, at the default ServerSpec."""
    async with _booted(cache_dir, tmp_path_factory.mktemp("reference")) as instance:
        yield instance


@pytest.fixture
def boot_reference(cache_dir: Path, tmp_path: Path) -> BootReference:
    """Boot a Reference of the test's own, with ServerSpec changes such as view_distance=4."""
    return functools.partial(_booted, cache_dir, tmp_path / "reference")


@pytest.fixture(scope="session")
def reference_attached(reference: Instance) -> Attached:
    """The session's Reference Instance as a Run's Attached side (the fixture owns it)."""
    return Attached(name=VanillaAdapter.name, spec=_spec(reference.endpoint))


@contextlib.asynccontextmanager
async def _booted(cache_dir: Path, workdir: Path, **changes: object) -> AsyncIterator[Instance]:
    """A Reference Instance at the default ServerSpec with `changes`, on a host of its own.

    Leak-guarded like any process-starting test (docs/PROCESS.md Worker contract):
    its LaunchPlan's environment carries a token unique to it, and once `running` has
    stopped it, anything still tagged with that token is a leak, and is killed and
    reported as a test failure.
    """
    adapter = VanillaAdapter()
    installation = install.require(adapter, TARGET, cache_dir)
    endpoint = free_endpoint()  # a loopback host of its own: no other Instance shares it
    spec = dataclasses.replace(_spec(endpoint), **changes)
    plan = adapter.prepare(installation, spec, workdir)
    token = f"{_TOKEN_VAR}={uuid.uuid4().hex}"
    plan = dataclasses.replace(plan, env={**plan.env, _TOKEN_VAR: token.partition("=")[2]})
    try:
        async with running(
            plan,
            ready=status_probe(TARGET),
            ready_timeout=READY_TIMEOUT_S,
            stop_timeout=STOP_TIMEOUT_S,
        ) as instance:
            yield instance
    finally:
        leaked = kill_survivors(token)
    assert not leaked, f"the reference Instance's process group outlived it: {leaked}"


def _spec(endpoint: Endpoint) -> ServerSpec:
    """The ServerSpec the session's Reference is launched from: the default, at `endpoint`."""
    return ServerSpec(host=endpoint.host, port=endpoint.port)
