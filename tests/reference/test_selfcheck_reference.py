"""G2 for the status Scenarios: their Self-check is `match` in 20 out of 20 runs.

Two Reference Instances of their own (a Self-check compares two, each at its own
Endpoint), booted once and reused for all 20 repetitions.
"""

import dataclasses
import uuid
from pathlib import Path

import pytest
from support.leak_guard import kill_survivors

from mscts.adapters.base import Installation, LaunchPlan
from mscts.adapters.vanilla import VanillaAdapter
from mscts.compare import Outcome
from mscts.run import Server, selfcheck
from mscts.spec import ServerSpec
from mscts.target import TARGET, Target

_TOKEN_VAR = "MSCTS_SELFCHECK_TOKEN"  # noqa: S105 - an env var name, not a secret
_REPEAT = 20


@dataclasses.dataclass
class _Tagged:
    """VanillaAdapter, with a leak-guard token in every LaunchPlan's environment."""

    token: str
    name: str = "vanilla"
    vanilla: VanillaAdapter = dataclasses.field(default_factory=VanillaAdapter)
    binary: str = "server.jar"

    def check(self, binary: Path, target: Target) -> None:
        self.vanilla.check(binary, target)

    def provision(self, target: Target, cache_dir: Path) -> Installation:
        return self.vanilla.provision(target, cache_dir)

    def prepare(self, installation: Installation, spec: ServerSpec, workdir: Path) -> LaunchPlan:
        plan = self.vanilla.prepare(installation, spec, workdir)
        return dataclasses.replace(plan, env={**plan.env, _TOKEN_VAR: self.token})


@pytest.mark.reference
@pytest.mark.asyncio
@pytest.mark.timeout(300)  # two boots, and 40 status exchanges
async def test_selfcheck_of_the_status_scenarios_matches_20_of_20(
    cache_dir: Path, tmp_path: Path
) -> None:
    adapter = _Tagged(token=uuid.uuid4().hex)
    reference = Server(adapter, adapter.provision(TARGET, cache_dir))
    try:
        verdicts = await selfcheck(
            ["status/basic", "status/ping"],
            reference=reference,
            workdir=tmp_path / "selfcheck",
            repeat=_REPEAT,
        )
    finally:
        leaked = kill_survivors(f"{_TOKEN_VAR}={adapter.token}")
    assert not leaked, f"a Reference Instance outlived the Self-check: {leaked}"

    assert [v.scenario_id for v in verdicts] == ["status/basic", "status/ping"] * _REPEAT
    not_matching = [v for v in verdicts if v.outcome is not Outcome.MATCH]
    assert not_matching == []
