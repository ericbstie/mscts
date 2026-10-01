"""An Observation window around a Control command makes a gameplay Group's Self-check match.

The probe Group (`support.probe.SETBLOCK_OBSERVED`) joins a Bot, has Control set a block
inside a window, and compares what the Bot sees of it. Two Reference Instances of the
test's own play it 20 times each.
"""

import dataclasses
import uuid
from pathlib import Path

import pytest
from support.leak_guard import kill_survivors
from support.probe import SETBLOCK_OBSERVED

from mscts import install
from mscts.adapters.base import Installation, LaunchPlan
from mscts.adapters.vanilla import VanillaAdapter
from mscts.compare import Outcome
from mscts.run import Server, run_results
from mscts.spec import ServerSpec
from mscts.target import TARGET, Target

_TOKEN_VAR = "MSCTS_OBSERVE_TOKEN"  # noqa: S105 - an env var name, not a secret
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

    def prepare(self, installation: Installation, spec: ServerSpec, workdir: Path) -> LaunchPlan:
        plan = self.vanilla.prepare(installation, spec, workdir)
        return dataclasses.replace(plan, env={**plan.env, _TOKEN_VAR: self.token})


@pytest.mark.reference
@pytest.mark.asyncio
@pytest.mark.timeout(600)  # two boots, then 20 plays of two joins and a window on each side
async def test_a_group_that_sets_a_block_inside_a_window_self_checks_20_of_20(
    cache_dir: Path, tmp_path: Path
) -> None:
    adapter = _Tagged(token=uuid.uuid4().hex)
    reference = Server(adapter, install.require(adapter, TARGET, cache_dir))
    try:
        result = await run_results(
            [SETBLOCK_OBSERVED],
            reference,
            reference,
            workdir=tmp_path / "selfcheck",
            repeat=_REPEAT,
        )
    finally:
        leaked = kill_survivors(f"{_TOKEN_VAR}={adapter.token}")
    assert not leaked, f"a Reference Instance outlived the Self-check: {leaked}"

    verdicts = result.verdicts
    assert len(verdicts) == _REPEAT
    not_matching = [v for v in verdicts if v.outcome is not Outcome.MATCH]
    assert not_matching == [], not_matching
    # Of play, it compared what the command did, and nothing the server sent on a clock,
    # nor anything Control received (its feedback is a system_chat).
    test_cases = set(verdicts[0].test_cases)
    assert "block_update" in test_cases, test_cases
    outside = {"set_time", "play:keep_alive", "award_stats", "login", "system_chat"}
    assert not outside & test_cases, test_cases
