"""Booting live Instances and giving a Run its own Reference Instances.

The Reference, Candidate and Self-check tiers share `booted` and its leak guard.
A test that gives a Run a Reference to launch Instances from itself uses `own_reference`.
"""

import contextlib
import dataclasses
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

from mscts import install
from mscts.adapters.base import Adapter, Build, Fetch, Installation, LaunchPlan, Release
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
_TOKEN_VAR = "MSCTS_LIVE_TEST_TOKEN"  # noqa: S105 - an env var name, not a secret


@contextlib.asynccontextmanager
async def booted(
    cache_dir: Path,
    workdir: Path,
    *,
    adapter: Adapter | None = None,
    plan: LaunchPlan | None = None,
    stop_timeout: float = STOP_TIMEOUT_S,
    **changes: object,
) -> AsyncIterator[Instance]:
    """Boot `adapter` at the default ServerSpec with `changes`, or reuse a prepared `plan`.

    Defaults to VanillaAdapter. A prepared plan keeps its Endpoint and workdir, for a warm
    boot or a Group's ServerSpec; `changes` apply only when preparing a fresh plan.

    Leak-guarded like any process-starting test (docs/PROCESS.md Worker contract):
    its LaunchPlan's environment carries a token unique to it, and once `running` has
    stopped it, anything still tagged with that token is a leak, and is killed and
    reported as a test failure.
    """
    if plan is None:
        adapter = adapter if adapter is not None else VanillaAdapter()
        installation = install.require(adapter, TARGET, cache_dir)
        endpoint = free_endpoint()  # a loopback host of its own: no other Instance shares it
        spec = dataclasses.replace(default_spec(endpoint), **changes)
        plan = adapter.prepare(installation, spec, workdir)
    elif changes:
        msg = "ServerSpec changes cannot be applied to a prepared LaunchPlan"
        raise ValueError(msg)
    token = f"{_TOKEN_VAR}={uuid.uuid4().hex}"
    plan = dataclasses.replace(plan, env={**plan.env, _TOKEN_VAR: token.partition("=")[2]})
    try:
        async with running(
            plan,
            ready=status_probe(TARGET),
            ready_timeout=READY_TIMEOUT_S,
            stop_timeout=stop_timeout,
        ) as instance:
            yield instance
    finally:
        leaked = kill_survivors(token, within=3.0)
        assert not leaked, f"the Instance's process group outlived it: {leaked}"


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
    latest_aliases: frozenset[str] = frozenset[str]()

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
