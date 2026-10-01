"""The probe Group, with its Observation window, plays to the end against Pumpkin.

Pumpkin answers the window's barrier (`Bot.sync`), so the Group completes; whatever it
sent inside the window is the Comparison's business, not this test's.
"""

import dataclasses
import uuid
from pathlib import Path

import pytest
from support.commands import SETBLOCK_OBSERVED, allow_commands
from support.leak_guard import kill_survivors

from mscts import install
from mscts.adapters.pumpkin import PumpkinAdapter
from mscts.bot import status_probe
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.run import run_group
from mscts.runner import free_endpoint, running
from mscts.spec import ServerSpec
from mscts.target import TARGET

pytestmark = pytest.mark.candidate

_GUARD = "MSCTS_LEAK_GUARD"


@pytest.mark.asyncio
@pytest.mark.timeout(180)
async def test_the_probe_group_completes_against_pumpkin(
    cache_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_commands(monkeypatch)
    endpoint = free_endpoint()
    spec = SETBLOCK_OBSERVED.spec(ServerSpec(host=endpoint.host, port=endpoint.port))
    adapter = PumpkinAdapter()
    plan = adapter.prepare(install.require(adapter, TARGET, cache_dir), spec, tmp_path / "pumpkin")
    token = uuid.uuid4().hex
    plan = dataclasses.replace(plan, env={**plan.env, _GUARD: token})
    try:
        async with running(
            plan, ready=status_probe(TARGET), ready_timeout=60, stop_timeout=30
        ) as instance:
            transcript = await run_group(SETBLOCK_OBSERVED, instance.endpoint, server="pumpkin")
    finally:
        leaked = kill_survivors(f"{_GUARD}={token}", within=3.0)
    assert not leaked, f"Pumpkin processes outlived the test: {leaked}"

    labels = [mark.label for mark in transcript.marks]
    assert labels == [
        f"{OBSERVE_OPEN} minecraft:block_update minecraft:system_chat",
        OBSERVE_CLOSE,
    ]
    answers = [e.bot for e in transcript.events if e.packet.name == "minecraft:award_stats"]
    assert sorted(set(answers)) == ["mscts_op", "watcher"], answers
