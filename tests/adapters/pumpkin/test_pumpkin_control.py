"""Control against Pumpkin: a command answers, and another Bot sees what it did.

Also, Pumpkin honours the Fixture world's game rules the Adapter writes (ADR-0013).
"""

from pathlib import Path

import pytest
from support.reference import booted

from mscts.adapters.pumpkin import PumpkinAdapter
from mscts.codec.packets import Packet
from mscts.codec.schema import POSITION
from mscts.codec.wire import Reader
from mscts.group import GroupContext
from mscts.net import Endpoint
from mscts.transcript import Transcript

pytestmark = pytest.mark.candidate

_TIMEOUT_S = 10.0
BLOCK = {"x": 1, "y": -60, "z": 1}
SETBLOCK = "setblock 1 -60 1 minecraft:stone"


def at_block(packet: Packet) -> bool:
    """Whether a `block_update` is for BLOCK: its payload starts with the position."""
    return POSITION.read(Reader(packet.payload)) == BLOCK


async def set_a_block(endpoint: Endpoint, transcript: Transcript) -> tuple[Packet, ...]:
    """Join a watcher, have Control set BLOCK, and wait for the watcher to see it."""
    context = GroupContext(endpoint, transcript, timeout_s=_TIMEOUT_S)
    try:
        watcher = await context.bot("watcher")
        await watcher.join()
        said = await context.control.run(SETBLOCK)
        await watcher.expect("minecraft:block_update", timeout_s=_TIMEOUT_S, where=at_block)
    finally:
        await context.close()
    return said


async def ask_spawn_mobs(endpoint: Endpoint, transcript: Transcript) -> tuple[Packet, ...]:
    """Have Control ask for the `spawn_mobs` game rule, and return Pumpkin's answer."""
    context = GroupContext(endpoint, transcript, timeout_s=_TIMEOUT_S)
    try:
        return await context.control.run("gamerule spawn_mobs")
    finally:
        await context.close()


@pytest.mark.asyncio
@pytest.mark.timeout(180)
async def test_control_gets_an_answer_and_another_bot_sees_the_block(
    cache_dir: Path, tmp_path: Path
) -> None:
    transcript = Transcript(group_id="candidate/control", server="pumpkin")
    async with booted(cache_dir, tmp_path / "pumpkin", adapter=PumpkinAdapter()) as instance:
        said = await set_a_block(instance.endpoint, transcript)

    assert said, "Pumpkin answered the setblock with no system_chat"


@pytest.mark.asyncio
@pytest.mark.timeout(180)
async def test_mob_spawning_is_off_in_the_fixture_world(cache_dir: Path, tmp_path: Path) -> None:
    # Pumpkin falls back to its defaults, spawning on, if it cannot read game_rules.dat.
    transcript = Transcript(group_id="candidate/spawn-mobs", server="pumpkin")
    async with booted(cache_dir, tmp_path / "pumpkin", adapter=PumpkinAdapter()) as instance:
        said = await ask_spawn_mobs(instance.endpoint, transcript)

    assert any(b"false" in packet.payload for packet in said), said
