"""The movement schemas a Bot sends as its player moves, round-tripped through hand-built bytes."""

import struct
from collections.abc import Mapping

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, State

CODEC = Codec.load("26.3")
SERVERBOUND = Direction.SERVERBOUND


def round_trip(name: str, fields: Mapping[str, object], data: bytes) -> None:
    assert CODEC.packet_id(State.PLAY, SERVERBOUND, name) == data[0]
    assert CODEC.encode(State.PLAY, SERVERBOUND, name, fields) == data
    packet = CODEC.decode(State.PLAY, SERVERBOUND, data)
    assert (packet.name, packet.fields) == (name, fields)


def doubles(*values: float) -> bytes:
    return struct.pack(f">{len(values)}d", *values)


def floats(*values: float) -> bytes:
    return struct.pack(f">{len(values)}f", *values)


def test_move_player_pos_is_a_position_and_flags() -> None:
    fields = {"x": 6.5, "y": -60.0, "z": 7.25, "flags": 0x01}  # on ground
    round_trip(
        "minecraft:move_player_pos", fields, bytes([0x1E]) + doubles(6.5, -60.0, 7.25) + b"\x01"
    )


def test_move_player_pos_rot_is_a_position_a_rotation_and_flags() -> None:
    fields = {"x": 6.5, "y": -60.0, "z": 7.25, "yaw": -90.5, "pitch": 12.0, "flags": 0x03}
    data = bytes([0x1F]) + doubles(6.5, -60.0, 7.25) + floats(-90.5, 12.0) + b"\x03"
    round_trip("minecraft:move_player_pos_rot", fields, data)


def test_move_player_rot_is_a_rotation_and_flags() -> None:
    fields = {"yaw": 400.0, "pitch": -90.0, "flags": 0x00}
    round_trip("minecraft:move_player_rot", fields, bytes([0x20]) + floats(400.0, -90.0) + b"\x00")


def test_move_player_status_only_is_the_flags() -> None:
    round_trip("minecraft:move_player_status_only", {"flags": 0x02}, bytes([0x21, 0x02]))


def test_player_command_is_the_entity_id_the_action_and_the_jump_boost() -> None:
    fields = {"entity_id": 300, "action": 1, "jump_boost": 0}  # start sprinting
    round_trip("minecraft:player_command", fields, bytes([0x2A, 0xAC, 0x02, 0x01, 0x00]))


def test_player_command_refuses_an_action_past_the_last() -> None:
    # Vanilla reads the action with readEnum: 7 constants, so 7 is out of range.
    with pytest.raises(CodecError, match="action: 7 is not an ordinal of 0 to 6"):
        CODEC.decode(State.PLAY, SERVERBOUND, bytes([0x2A, 0x01, 0x07, 0x00]))


def test_player_input_is_one_byte_of_key_flags() -> None:
    round_trip(
        "minecraft:player_input", {"flags": 0x70}, bytes([0x2B, 0x70])
    )  # jump, sneak, sprint


def test_client_tick_end_has_no_fields() -> None:
    round_trip("minecraft:client_tick_end", {}, bytes([0x0D]))
