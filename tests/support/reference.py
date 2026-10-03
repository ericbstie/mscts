"""Booting a vanilla Reference Instance for a test, the way every live tier does it.

The reference tier (`tests/reference/conftest.py`) and the Self-check tier
(`tests/selfcheck/conftest.py`) both boot Reference Instances, so how one is booted and
leak-guarded lives here. A test that gives a Run a Reference to launch Instances from
itself uses `own_reference`.
"""

import contextlib
import dataclasses
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

from mscts import install
from mscts.adapters.base import Build, Fetch, Installation, LaunchPlan, Release
from mscts.adapters.vanilla import VanillaAdapter
from mscts.bot import status_probe
from mscts.net import Endpoint
from mscts.run import Attached, Server
from mscts.runner import Instance, free_endpoint, running
from mscts.spec import ServerSpec
from mscts.target import TARGET, Target
from support.leak_guard import kill_survivors

READY_TIMEOUT_S = 120  # a cold first boot unpacks the bundled libraries and makes a world
STOP_TIMEOUT_S = 30
_TOKEN_VAR = "MSCTS_REFERENCE_TOKEN"  # noqa: S105 - an env var name, not a secret


@contextlib.asynccontextmanager
async def booted(cache_dir: Path, workdir: Path, **changes: object) -> AsyncIterator[Instance]:
    """A Reference Instance at the default ServerSpec with `changes`, on a host of its own.

    Leak-guarded like any process-starting test (docs/PROCESS.md Worker contract):
    its LaunchPlan's environment carries a token unique to it, and once `running` has
    stopped it, anything still tagged with that token is a leak, and is killed and
    reported as a test failure.
    """
    adapter = VanillaAdapter()
    installation = install.require(adapter, TARGET, cache_dir)
    endpoint = free_endpoint()  # a loopback host of its own: no other Instance shares it
    spec = dataclasses.replace(default_spec(endpoint), **changes)
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


def default_spec(endpoint: Endpoint) -> ServerSpec:
    """The ServerSpec a test's Reference is launched from: the default, at `endpoint`."""
    return ServerSpec(host=endpoint.host, port=endpoint.port)


def attached(instance: Instance) -> Attached:
    """`instance`, a Reference booted at the default ServerSpec, as a Run's Attached side."""
    return Attached(name=VanillaAdapter.name, spec=default_spec(instance.endpoint))


@dataclasses.dataclass
class _Tagged:
    """VanillaAdapter, with a leak-guard token in every LaunchPlan's environment."""

    token: str
    name: str = VanillaAdapter.name
    vanilla: VanillaAdapter = dataclasses.field(default_factory=VanillaAdapter)
    binary: str = "server.jar"

    def release(self, target: Target, version: str | None, fetch: Fetch) -> Release:
        return self.vanilla.release(target, version, fetch)

    def check(self, binary: Path, target: Target) -> Build:
        return self.vanilla.check(binary, target)

    def prepare(self, installation: Installation, spec: ServerSpec, workdir: Path) -> LaunchPlan:
        plan = self.vanilla.prepare(installation, spec, workdir)
        return dataclasses.replace(plan, env={**plan.env, _TOKEN_VAR: self.token})


@contextlib.contextmanager
def own_reference(cache_dir: Path) -> Iterator[Server]:
    """A Reference side for a Run that launches the Instances itself, leak-guarded.

    Pass it as both sides to `run` for a Self-check on Instances of the Run's own, one pair
    for each ServerSpec its Groups make. Once the block ends, anything still tagged with
    the token unique to it is a leak, and is killed and reported as a test failure.
    """
    adapter = _Tagged(token=uuid.uuid4().hex)
    try:
        yield Server(adapter, install.require(adapter, TARGET, cache_dir))
    finally:
        leaked = kill_survivors(f"{_TOKEN_VAR}={adapter.token}")
    assert not leaked, f"a Reference Instance outlived the Run: {leaked}"
