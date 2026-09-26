"""Play schemas of Target 26.3 that the Bot handles, round-tripped through hand-built bytes."""

import struct
from collections.abc import Mapping

import pytest

from mscts.codec.packets import Codec, Direction, State

CODEC = Codec.load("26.3")
CLIENTBOUND, SERVERBOUND = Direction.CLIENTBOUND, Direction.SERVERBOUND


def round_trip(direction: Direction, name: str, fields: Mapping[str, object], data: bytes) -> None:
    assert CODEC.packet_id(State.PLAY, direction, name) == data[0]
    assert CODEC.encode(State.PLAY, direction, name, fields) == data
    packet = CODEC.decode(State.PLAY, direction, data)
    assert (packet.name, packet.fields) == (name, fields)


def doubles(*values: float) -> bytes:
    return struct.pack(f">{len(values)}d", *values)


def floats(*values: float) -> bytes:
    return struct.pack(f">{len(values)}f", *values)


def test_player_position_is_id_pose_velocity_rotation_and_flags() -> None:
    fields = {
        "teleport_id": 1,
        "x": 6.5,
        "y": -60.0,
        "z": 7.5,
        "velocity_x": 0.0,
        "velocity_y": 0.0,
        "velocity_z": 0.0,
        "yaw": -90.5,
        "pitch": 0.0,
        "flags": 0x18,  # relative yaw and pitch
    }
    data = (
        bytes([0x49, 0x01])
        + doubles(6.5, -60.0, 7.5, 0.0, 0.0, 0.0)
        + floats(-90.5, 0.0)
        + bytes.fromhex("00000018")
    )
    round_trip(CLIENTBOUND, "minecraft:player_position", fields, data)


def test_accept_teleportation_echoes_the_pose() -> None:
    fields = {"teleport_id": 1, "x": 6.5, "y": -60.0, "z": 7.5, "yaw": -90.5, "pitch": 0.0}
    data = bytes([0x00, 0x01]) + doubles(6.5, -60.0, 7.5) + floats(-90.5, 0.0)
    round_trip(SERVERBOUND, "minecraft:accept_teleportation", fields, data)


@pytest.mark.parametrize(("direction", "packet_id"), [(CLIENTBOUND, 0x2D), (SERVERBOUND, 0x1C)])
def test_keep_alive_is_a_long_both_ways(direction: Direction, packet_id: int) -> None:
    data = bytes([packet_id]) + (1_790_000_000_000).to_bytes(8, "big")
    round_trip(direction, "minecraft:keep_alive", {"keep_alive_id": 1_790_000_000_000}, data)


def test_the_chunk_batch_packets() -> None:
    round_trip(CLIENTBOUND, "minecraft:chunk_batch_start", {}, bytes([0x0C]))
    round_trip(CLIENTBOUND, "minecraft:chunk_batch_finished", {"batch_size": 9}, bytes([0x0B, 9]))
    round_trip(
        SERVERBOUND,
        "minecraft:chunk_batch_received",
        {"chunks_per_tick": 9.0},
        bytes([0x0B]) + floats(9.0),
    )


def test_the_configuration_switch_packets_have_no_fields() -> None:
    round_trip(CLIENTBOUND, "minecraft:start_configuration", {}, bytes([0x78]))
    round_trip(SERVERBOUND, "minecraft:configuration_acknowledged", {}, bytes([0x10]))


def test_update_tags_in_play_is_registries_of_tags_of_ids() -> None:
    # The same ClientboundUpdateTagsPacket as in configuration, under play id 137.
    data = (
        bytes.fromhex("8901 01")  # id 137 as a VarInt; one registry
        + bytes([14])
        + b"minecraft:item"
        + bytes([0x01, 14])
        + b"minecraft:logs"
        + bytes.fromhex("03 00 7f 8001")  # entries 0, 127 and 128
    )
    fields = {
        "tagged_registries": [
            {
                "registry": "minecraft:item",
                "tags": [{"tag_name": "minecraft:logs", "entries": [0, 127, 128]}],
            }
        ]
    }
    assert CODEC.packet_id(State.PLAY, CLIENTBOUND, "minecraft:update_tags") == 137
    assert CODEC.encode(State.PLAY, CLIENTBOUND, "minecraft:update_tags", fields) == data
    packet = CODEC.decode(State.PLAY, CLIENTBOUND, data)
    assert (packet.name, packet.fields) == ("minecraft:update_tags", fields)


LOGIN = {
    "entity_id": 42,
    "is_hardcore": False,
    "dimension_names": ["minecraft:overworld", "minecraft:the_end"],
    "max_players": 20,
    "view_distance": 2,
    "simulation_distance": 2,
    "reduced_debug_info": False,
    "enable_respawn_screen": True,
    "do_limited_crafting": False,
    "dimension_type": 0,
    "dimension_name": "minecraft:overworld",
    "hashed_seed": -1,
    "game_mode": 0,
    "previous_game_mode": 0,
    "is_debug": False,
    "is_flat": True,
    "death_location": None,
    "portal_cooldown": 0,
    "sea_level": -63,
    "online_mode": False,
    "enforces_secure_chat": False,
}


def string(text: str) -> bytes:
    return bytes([len(text)]) + text.encode()


LOGIN_BYTES = (
    bytes([0x32])  # id: minecraft:login
    + (42).to_bytes(4, "big")
    + b"\x00"
    + b"\x02"
    + string("minecraft:overworld")
    + string("minecraft:the_end")
    + bytes([20, 2, 2])
    + b"\x00\x01\x00"
    + b"\x00"
    + string("minecraft:overworld")
    + b"\xff" * 8
    + b"\x00\x00"
    + b"\x00\x01"
    + b"\x00"  # no death location
    + b"\x00"
    + bytes.fromhex("c1ffffff0f")  # sea level -63
    + b"\x00\x00"
)


def test_login_decodes_every_field_in_order() -> None:
    round_trip(CLIENTBOUND, "minecraft:login", LOGIN, LOGIN_BYTES)


def test_login_death_location_is_a_dimension_and_a_position() -> None:
    death = {
        "death_dimension_name": "minecraft:the_nether",
        "death_location": {"x": 1, "y": -2, "z": 3},
    }
    fields = {**LOGIN, "death_location": death}
    encoded = CODEC.encode(State.PLAY, CLIENTBOUND, "minecraft:login", fields)
    assert CODEC.decode(State.PLAY, CLIENTBOUND, encoded).fields == fields
