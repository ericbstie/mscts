"""The probe Group, with its Observation window, plays to the end against Pumpkin.

Pumpkin answers the window's barrier (`Bot.sync`), so the Group completes; whatever it
sent inside the window is the Comparison's business, not this test's.
"""

from pathlib import Path

import pytest
from support.probe import SETBLOCK_OBSERVED, WATCHER
from support.reference import booted

from mscts import install
from mscts.adapters.pumpkin import PumpkinAdapter
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.run import run_group
from mscts.runner import free_endpoint
from mscts.spec import ServerSpec
from mscts.target import TARGET

pytestmark = pytest.mark.candidate


@pytest.mark.asyncio
@pytest.mark.timeout(180)
async def test_the_probe_group_completes_against_pumpkin(cache_dir: Path, tmp_path: Path) -> None:
    endpoint = free_endpoint()
    spec = SETBLOCK_OBSERVED.spec(ServerSpec(host=endpoint.host, port=endpoint.port))
    adapter = PumpkinAdapter()
    workdir = tmp_path / "pumpkin"
    plan = adapter.prepare(install.require(adapter, TARGET, cache_dir), spec, workdir)
    async with booted(cache_dir, workdir, plan=plan) as instance:
        transcript = await run_group(SETBLOCK_OBSERVED, instance.endpoint, server="pumpkin")

    labels = [mark.label for mark in transcript.marks]
    assert labels[0] == f"{OBSERVE_OPEN} minecraft:block_update"
    closes = [f"{OBSERVE_CLOSE} {bot}" for bot in ("control", WATCHER)]
    assert sorted(labels[1:]) == sorted((OBSERVE_CLOSE, *closes))
    answers = [e.bot for e in transcript.events if e.packet.name == "minecraft:award_stats"]
    assert sorted(set(answers)) == ["control", WATCHER], answers
