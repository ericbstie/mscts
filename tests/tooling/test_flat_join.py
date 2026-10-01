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


@pytest.mark.parametrize("corrections", [1, 2, 14])
def test_the_same_pose_again_with_the_next_ids_is_a_flat_join(corrections: int) -> None:
    positions = [position(number) for number in range(1, corrections + 2)]
    assert unlike_a_flat_join(positions) == []


@pytest.mark.parametrize(
    "later",
    [position(3), position(2, x=0.5), position(2, yaw=90.0), position(2, flags=1)],
    ids=["an id skipped", "another x", "another yaw", "relative flags"],
)
def test_a_later_player_position_that_is_not_the_first_again_is_a_difference(
    later: Packet,
) -> None:
    assert unlike_a_flat_join([position(1), later]) == [
        "player_position 2 is not the first one's pose with teleport id 2"
    ]


def test_the_first_player_position_stands_on_the_top_layer() -> None:
    assert unlike_a_flat_join([position(1, y=63.0)]) == [
        f"the first player_position is at y=63.0, not {FLAT_SPAWN_Y}"
    ]
