"""The world time schema, round-tripped through payloads vanilla 26.3 sent.

The payloads are recorded in docs/research/2026-10-15-day-cycle.md.
"""

import pytest

from mscts.codec.packets import Codec, Direction, State

CODEC = Codec.load("26.3")
SET_TIME = 0x73


def _clock(clock: int, total_ticks: int) -> dict[str, object]:
    return {"clock": clock, "total_ticks": total_ticks, "partial_tick": 0.0, "rate": 1.0}


@pytest.mark.parametrize(
    ("payload", "fields"),
    [
        # The 20-tick heartbeat: game time only, no clock.
        ("000000000000002700", {"game_time": 0x27, "clocks": []}),
        # `time set 1000`: the one clock it changed.
        (
            "00000000000000300100e807000000003f800000",
            {"game_time": 0x30, "clocks": [_clock(0, 1000)]},
        ),
        # The join: every clock, the overworld's and the end's.
        (
            "000000000000001e02001e000000003f800000011e000000003f800000",
            {"game_time": 0x1E, "clocks": [_clock(0, 0x1E), _clock(1, 0x1E)]},
        ),
    ],
    ids=["heartbeat", "time-set", "join"],
)
def test_set_time_is_the_game_time_then_each_clock(payload: str, fields: dict[str, object]) -> None:
    data = bytes([SET_TIME]) + bytes.fromhex(payload)

    assert CODEC.packet_id(State.PLAY, Direction.CLIENTBOUND, "minecraft:set_time") == SET_TIME
    packet = CODEC.decode(State.PLAY, Direction.CLIENTBOUND, data)
    assert (packet.name, packet.fields) == ("minecraft:set_time", fields)
    assert CODEC.encode(State.PLAY, Direction.CLIENTBOUND, "minecraft:set_time", fields) == data
