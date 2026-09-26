"""What a Bot answers by itself, as each packet arrives, the way the vanilla client does."""

import asyncio
import math
from typing import TYPE_CHECKING, cast

import pytest

from mscts.bot import CHUNKS_PER_TICK, Replies
from mscts.codec.packets import Direction, Packet, State

if TYPE_CHECKING:
    from mscts.net import Connection


class Sent:
    """A stand-in Connection that only records what is sent through it."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, object]]] = []

    async def send(self, name: str, /, **fields: object) -> None:
        self.sent.append((name, fields))


def arrived(state: State, name: str, **fields: object) -> Packet:
    return Packet(
        state=state,
        direction=Direction.CLIENTBOUND,
        name=name,
        packet_id=0,
        payload=b"",
        fields=fields,
    )


def answers(replies: Replies, *packets: Packet) -> list[tuple[str, dict[str, object]]]:
    connection = Sent()

    async def feed() -> None:
        for packet in packets:
            await replies(cast("Connection", connection), packet)

    asyncio.run(feed())
    return connection.sent


def teleport(teleport_id: int, **pose: object) -> Packet:
    fields: dict[str, object] = {
        "teleport_id": teleport_id,
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "velocity_x": 0.0,
        "velocity_y": 0.0,
        "velocity_z": 0.0,
        "yaw": 0.0,
        "pitch": 0.0,
        "flags": 0,
    }
    fields.update(pose)
    return arrived(State.PLAY, "minecraft:player_position", **fields)


@pytest.mark.parametrize("state", [State.CONFIGURATION, State.PLAY])
def test_a_keep_alive_is_echoed(state: State) -> None:
    packet = arrived(state, "minecraft:keep_alive", keep_alive_id=-5)
    assert answers(Replies(), packet) == [("minecraft:keep_alive", {"keep_alive_id": -5})]


@pytest.mark.parametrize(
    ("state", "received", "reply"),
    [
        (State.LOGIN, "minecraft:login_finished", "minecraft:login_acknowledged"),
        (State.CONFIGURATION, "minecraft:finish_configuration", "minecraft:finish_configuration"),
        (State.CONFIGURATION, "minecraft:code_of_conduct", "minecraft:accept_code_of_conduct"),
        (State.PLAY, "minecraft:start_configuration", "minecraft:configuration_acknowledged"),
    ],
)
def test_the_acks_are_sent_as_the_packet_arrives(state: State, received: str, reply: str) -> None:
    assert answers(Replies(), arrived(state, received)) == [(reply, {})]


def test_the_known_packs_offered_are_echoed() -> None:
    # The vanilla client answers with the offered packs it knows, in the server's order
    # (KnownPacksManager.trySelectingPacks, javap); for vanilla's offer, that is all of them.
    packs = [{"namespace": "minecraft", "id": "core", "version": "26.3"}]
    packet = arrived(State.CONFIGURATION, "minecraft:select_known_packs", known_packs=packs)
    assert answers(Replies(), packet) == [("minecraft:select_known_packs", {"known_packs": packs})]


def test_a_chunk_batch_is_acknowledged_at_a_fixed_rate() -> None:
    packet = arrived(State.PLAY, "minecraft:chunk_batch_finished", batch_size=9)
    assert answers(Replies(), packet) == [
        ("minecraft:chunk_batch_received", {"chunks_per_tick": CHUNKS_PER_TICK})
    ]
    assert CHUNKS_PER_TICK == 9.0  # vanilla's PlayerChunkSender START_CHUNKS_PER_TICK


@pytest.mark.parametrize(
    ("state", "name"),
    [
        (State.CONFIGURATION, "minecraft:registry_data"),
        (State.PLAY, "minecraft:login"),
        (State.PLAY, "minecraft:chunk_batch_start"),
        (State.LOGIN, "minecraft:login_compression"),
    ],
)
def test_other_packets_get_no_answer(state: State, name: str) -> None:
    assert answers(Replies(), arrived(state, name)) == []


def test_an_absolute_teleport_is_confirmed_with_the_pose_it_sets() -> None:
    # 26.3's accept_teleportation echoes the resulting pose (ClientPacketListener
    # .handleMovePlayer, javap), not just the id.
    packet = teleport(1, x=6.5, y=-60.0, z=7.5, velocity_y=-0.5, yaw=-90.5, pitch=12.0)
    assert answers(Replies(), packet) == [
        (
            "minecraft:accept_teleportation",
            {"teleport_id": 1, "x": 6.5, "y": -60.0, "z": 7.5, "yaw": -90.5, "pitch": 12.0},
        )
    ]


def test_relative_teleport_flags_add_to_the_current_pose() -> None:
    # PositionMoveRotation.calculateAbsolute: a flagged axis adds to the current value,
    # and pitch is clamped to -90..90.
    first = teleport(1, x=1.0, y=2.0, z=3.0, yaw=10.0, pitch=20.0)
    every_axis_relative = 0b11111
    second = teleport(2, x=1.0, y=1.0, z=1.0, yaw=5.0, pitch=80.0, flags=every_axis_relative)
    only_x_relative = 0b1
    third = teleport(3, x=0.5, y=9.0, z=9.0, flags=only_x_relative)
    sent = answers(Replies(), first, second, third)
    assert [fields for _, fields in sent] == [
        {"teleport_id": 1, "x": 1.0, "y": 2.0, "z": 3.0, "yaw": 10.0, "pitch": 20.0},
        {"teleport_id": 2, "x": 2.0, "y": 3.0, "z": 4.0, "yaw": 15.0, "pitch": 90.0},
        {"teleport_id": 3, "x": 2.5, "y": 9.0, "z": 9.0, "yaw": 0.0, "pitch": 0.0},
    ]


def test_relative_rotation_is_summed_in_binary32() -> None:
    # The client adds floats: 0.1f + 0.2f is 0.3000000119..., not the double 0.3.
    tenth, fifth = 0.10000000149011612, 0.20000000298023224  # 0.1f and 0.2f, exactly
    first = teleport(1, yaw=tenth)
    second = teleport(2, yaw=fifth, flags=0b1000)
    [_, (_, fields)] = answers(Replies(), first, second)
    assert fields["yaw"] == 0.30000001192092896


def test_a_rotation_that_is_not_finite_is_ignored_as_vanilla_does() -> None:
    # Entity.setYRot / setXRot keep the old value for a non-finite one.
    first = teleport(1, yaw=30.0, pitch=10.0)
    second = teleport(2, yaw=math.inf, pitch=math.nan)
    [_, (_, fields)] = answers(Replies(), first, second)
    assert (fields["yaw"], fields["pitch"]) == (30.0, 10.0)
