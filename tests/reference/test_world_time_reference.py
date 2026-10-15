"""The `set_time` schema against a live vanilla 26.3, sharing the session's one Reference.

A join sends every world clock, and the 20-tick heartbeat none: both decode with the Codec's
schema and encode back to the same bytes (docs/research/2026-10-15-day-cycle.md).
"""

from typing import TYPE_CHECKING, cast

import pytest

from mscts.bot import Bot
from mscts.codec.packets import Codec, Direction, Packet, State
from mscts.runner import Instance
from mscts.target import TARGET
from mscts.transcript import Transcript

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = [pytest.mark.reference, pytest.mark.asyncio(loop_scope="session")]

CODEC = Codec.load("26.3")
SET_TIME = "minecraft:set_time"
_TIMEOUT_S = 10.0
OVERWORLD, THE_END = 0, 1
"""The `minecraft:world_clock` registry ids (26.3 bootstrap order)."""


def _clocks(packet: Packet) -> list[int]:
    clocks = (packet.fields or {}).get("clocks")
    assert isinstance(clocks, list)
    return [cast("Mapping[str, int]", entry)["clock"] for entry in clocks]


async def test_a_join_sends_every_clock_and_the_heartbeat_none(reference: Instance) -> None:
    transcript = Transcript(group_id="reference/world-time", server="vanilla")
    bot = await Bot.connect(
        reference.endpoint, TARGET, name="world_time", transcript=transcript, timeout_s=_TIMEOUT_S
    )
    try:
        await bot.join()
        await bot.expect(SET_TIME, timeout_s=_TIMEOUT_S, where=lambda p: _clocks(p) == [])
    finally:
        await bot.close()
    packets = [
        event.packet
        for event in transcript.events
        if event.packet.direction is Direction.CLIENTBOUND and event.packet.name == SET_TIME
    ]
    for packet in packets:
        assert packet.fields is not None, packet.decode_error
        encoded = CODEC.encode(State.PLAY, packet.direction, packet.name, packet.fields)
        assert encoded == bytes([packet.packet_id]) + packet.payload
    assert sorted(_clocks(packets[0])) == [OVERWORLD, THE_END]
    assert _clocks(packets[-1]) == []
