"""The Reference's flat world at the default ServerSpec, as a joining Bot sees it.

Pins the facts in support.chunks that the Pumpkin Adapter's world save is checked against
(tests/adapters/pumpkin/test_pumpkin_world.py), on the session's shared Reference. The join may send
the first `player_position` again, so only what it repeats is asserted (docs/research/
2026-09-26-join.md, "More than one `player_position` at join").
"""

import pytest
from support.chunks import (
    OVERWORLD_SECTIONS,
    decode_chunk,
    play_packets,
    unlike_a_flat_join,
    unlike_the_reference_flat_world,
)

from mscts.bot import Bot
from mscts.runner import Instance
from mscts.target import TARGET
from mscts.transcript import Transcript

pytestmark = [pytest.mark.reference, pytest.mark.asyncio(loop_scope="session")]

_TIMEOUT_S = 10.0


async def test_a_bot_joins_a_flat_peaceful_world_at_y_minus_60(reference: Instance) -> None:
    transcript = Transcript(group_id="reference/flat-world", server="vanilla")
    bot = await Bot.connect(
        reference.endpoint, TARGET, name="flat_world", transcript=transcript, timeout_s=_TIMEOUT_S
    )
    try:
        await bot.join()
    finally:
        await bot.close()
    chunks = [
        decode_chunk(packet.payload, OVERWORLD_SECTIONS)
        for packet in play_packets(transcript, "minecraft:level_chunk_with_light")
    ]
    assert chunks
    assert [d for chunk in chunks for d in unlike_the_reference_flat_world(chunk)] == []
    assert unlike_a_flat_join(play_packets(transcript, "minecraft:player_position")) == []
    # Change Difficulty (wiki Packets, revision 3790659): an Unsigned Byte difficulty
    # (0 peaceful), then a Boolean, locked.
    (difficulty,) = play_packets(transcript, "minecraft:change_difficulty")
    assert difficulty.payload == b"\x00\x00"
