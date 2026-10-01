"""Block and world events against Pumpkin: what arrives, and what does not decode (#29).

The same script as the reference tier (`support.block_events`): Control runs the commands and
a watcher Bot receives their packets. Pumpkin may send these packets differently from vanilla,
so the test asserts only what a player could observe, that each window's packets arrive; what
fails to decode is listed in the failure message and in the research note as evidence, never
asserted away (docs/research/2026-10-01-block-world-events.md).
"""

import dataclasses
import uuid
from pathlib import Path

import pytest
from support.block_events import play, undecoded
from support.leak_guard import kill_survivors

from mscts import install
from mscts.adapters.pumpkin import PumpkinAdapter
from mscts.bot import status_probe
from mscts.group import GroupContext
from mscts.runner import free_endpoint, running
from mscts.spec import ServerSpec
from mscts.target import TARGET
from mscts.transcript import Transcript

pytestmark = pytest.mark.candidate

_GUARD = "MSCTS_LEAK_GUARD"
_TIMEOUT_S = 10.0


@pytest.mark.asyncio
@pytest.mark.timeout(240)
async def test_pumpkin_sends_the_block_and_world_events_and_its_decoding_is_listed(
    cache_dir: Path, tmp_path: Path
) -> None:
    endpoint = free_endpoint()
    spec = ServerSpec(host=endpoint.host, port=endpoint.port)
    adapter = PumpkinAdapter()
    plan = adapter.prepare(install.require(adapter, TARGET, cache_dir), spec, tmp_path / "pumpkin")
    token = uuid.uuid4().hex
    plan = dataclasses.replace(plan, env={**plan.env, _GUARD: token})
    transcript = Transcript(group_id="candidate/block-events", server="pumpkin")
    try:
        async with running(
            plan, ready=status_probe(TARGET), ready_timeout=60, stop_timeout=30
        ) as instance:
            context = GroupContext(instance.endpoint, transcript, timeout_s=_TIMEOUT_S)
            try:
                played = await play(context, transcript)
            finally:
                await context.close()
    finally:
        leaked = kill_survivors(f"{_GUARD}={token}", within=3.0)
    assert not leaked, f"Pumpkin processes outlived the test: {leaked}"

    for one in played:
        print(  # noqa: T201 - the evidence the research note quotes (pytest -s)
            f"{one.scenario.name}: missing={one.missing!r} "
            f"packets={[(p.name, p.decode_error) for p in one.packets]}"
        )
    print(f"undecoded: {undecoded(played)}")  # noqa: T201
    gaps = [
        f"{one.scenario.name}: {sorted(one.scenario.expects - one.names)} did not arrive"
        for one in played
        if not one.scenario.expects <= one.names
    ]
    assert not gaps, gaps
