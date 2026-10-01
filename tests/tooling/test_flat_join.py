"""The player_positions of a flat world join, as support.chunks says the Reference sends them.

A join gets teleport id 1 at the spawn, and sometimes more of the same pose, because the
server's speed check runs before its first tick (docs/research/2026-09-26-join.md, "More than
one player_position at join"), so how many is not something a test can assert.
"""

import pytest
from support.chunks import FLAT_SPAWN_Y, unlike_a_flat_join

from mscts.codec.packets import Direction, Packet, State


def position(teleport_id: int, **pose: object) -> Packet:
    fields: dict[str, object] = {
        "teleport_id": teleport_id,
        "x": -1.5,
        "y": FLAT_SPAWN_Y,
        "z": 10.5,
        "velocity_x": 0.0,
        "velocity_y": 0.0,
        "velocity_z": 0.0,
        "yaw": 0.0,
        "pitch": 0.0,
        "flags": 0,
    }
    fields.update(pose)
    return Packet(
        state=State.PLAY,
        direction=Direction.CLIENTBOUND,
        name="minecraft:player_position",
        packet_id=0,
        payload=b"",
        fields=fields,
    )


def test_one_player_position_at_the_spawn_is_a_flat_join() -> None:
    assert unlike_a_flat_join([position(1)]) == []


def test_a_join_without_a_player_position_is_not_one() -> None:
    assert unlike_a_flat_join([]) == ["no player_position"]


@pytest.mark.parametrize("teleport_id", [0, 2])
def test_the_first_player_position_is_teleport_id_1(teleport_id: int) -> None:
    assert unlike_a_flat_join([position(teleport_id)]) == [
        f"the first player_position has teleport id {teleport_id}, not 1"
    ]


def test_the_first_player_position_stands_on_the_top_layer() -> None:
    assert unlike_a_flat_join([position(1, y=63.0)]) == [
        f"the first player_position is at y=63.0, not {FLAT_SPAWN_Y}"
    ]
