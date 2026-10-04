"""The schemas a Bot uses to dig, place and use items, round-tripped through hand-built bytes."""

import struct
from collections.abc import Mapping

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, State

CODEC = Codec.load("26.3")
SERVERBOUND, CLIENTBOUND = Direction.SERVERBOUND, Direction.CLIENTBOUND

BLOCK = {"x": 3, "y": -60, "z": -2}
# x in the top 26 bits, z in the next 26, y in the low 12 (wiki Data types: Position).
BLOCK_BYTES = struct.pack(">q", 3 << 38 | (-2 & (1 << 26) - 1) << 12 | (-60 & 0xFFF))


def round_trip(direction: Direction, name: str, fields: Mapping[str, object], data: bytes) -> None:
    assert CODEC.packet_id(State.PLAY, direction, name) == data[0]
    assert CODEC.encode(State.PLAY, direction, name, fields) == data
    packet = CODEC.decode(State.PLAY, direction, data)
    assert (packet.name, packet.fields) == (name, fields)


def test_player_action_is_the_action_the_block_its_face_as_a_byte_and_the_sequence() -> None:
    fields = {"action": 3, "pos": BLOCK, "face": 1, "sequence": 300}  # stop digging, top face
    data = bytes([0x29, 0x03]) + BLOCK_BYTES + bytes([0x01, 0xAC, 0x02])
    round_trip(SERVERBOUND, "minecraft:player_action", fields, data)


def test_player_action_has_nine_actions() -> None:
    # 26.3's ServerboundPlayerActionPacket.Action has 9 constants, STAB the last (8); vanilla
    # reads it with readEnum, so 9 is out of range.
    stab = bytes([0x29, 0x08]) + BLOCK_BYTES + bytes([0x00, 0x00])
    assert CODEC.decode(State.PLAY, SERVERBOUND, stab).fields == {
        "action": 8,
        "pos": BLOCK,
        "face": 0,
        "sequence": 0,
    }
    with pytest.raises(CodecError, match="action: 9 is not an ordinal of 0 to 8"):
        CODEC.decode(State.PLAY, SERVERBOUND, bytes([0x29, 0x09]) + BLOCK_BYTES + b"\x00\x00")


def test_use_item_on_is_the_hand_the_block_hit_and_the_sequence() -> None:
    fields = {
        "hand": 1,
        "pos": BLOCK,
        "face": 5,
        "cursor_x": 0.5,
        "cursor_y": 1.0,
        "cursor_z": 0.25,
        "inside_block": True,
        "world_border_hit": False,
        "sequence": 2,
    }
    data = (
        bytes([0x42, 0x01])
        + BLOCK_BYTES
        + bytes([0x05])
        + struct.pack(">3f", 0.5, 1.0, 0.25)
        + bytes([0x01, 0x00, 0x02])
    )
    round_trip(SERVERBOUND, "minecraft:use_item_on", fields, data)


def test_use_item_is_the_hand_the_sequence_and_the_rotation() -> None:
    fields = {"hand": 0, "sequence": 7, "yaw": -90.5, "pitch": 12.0}
    data = bytes([0x43, 0x00, 0x07]) + struct.pack(">2f", -90.5, 12.0)
    round_trip(SERVERBOUND, "minecraft:use_item", fields, data)


def test_set_carried_item_is_the_slot_as_a_short() -> None:
    round_trip(SERVERBOUND, "minecraft:set_carried_item", {"slot": 8}, bytes([0x36, 0x00, 0x08]))


def test_punch_has_no_fields() -> None:
    round_trip(SERVERBOUND, "minecraft:punch", {}, bytes([0x2E]))


def test_block_changed_ack_is_the_sequence() -> None:
    data = bytes([CODEC.packet_id(State.PLAY, CLIENTBOUND, "minecraft:block_changed_ack"), 0x05])
    round_trip(CLIENTBOUND, "minecraft:block_changed_ack", {"sequence": 5}, data)


def test_set_held_slot_is_the_slot() -> None:
    data = bytes([CODEC.packet_id(State.PLAY, CLIENTBOUND, "minecraft:set_held_slot"), 0x04])
    round_trip(CLIENTBOUND, "minecraft:set_held_slot", {"slot": 4}, data)
