"""The container schemas, round-tripped through hand-built bytes (26.3 jar layouts, #28)."""

import struct
from collections.abc import Mapping

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, State

CODEC = Codec.load("26.3")
SERVERBOUND, CLIENTBOUND = Direction.SERVERBOUND, Direction.CLIENTBOUND

STONE = {"count": 64, "item": 1, "components": {"added": [], "removed": []}}
STONE_BYTES = bytes([0x40, 0x01, 0x00, 0x00])  # count, item, no components added or removed
HASHED_STONE = {"item": 1, "count": 64, "components": {"added": [], "removed": []}}
HASHED_STONE_BYTES = bytes([0x01, 0x01, 0x40, 0x00, 0x00])  # present, item, count, none, none
CHEST_TITLE = bytes([0x08, 0x00, 0x05]) + b"Chest"  # a network NBT String tag


def round_trip(direction: Direction, name: str, fields: Mapping[str, object], data: bytes) -> None:
    assert CODEC.packet_id(State.PLAY, direction, name) == data[0]
    assert CODEC.encode(State.PLAY, direction, name, fields) == data
    packet = CODEC.decode(State.PLAY, direction, data)
    assert (packet.name, packet.fields) == (name, fields)


def test_open_screen_is_the_window_its_menu_type_and_its_title() -> None:
    fields = {"window_id": 3, "window_type": 2, "window_title": CHEST_TITLE}
    round_trip(
        CLIENTBOUND, "minecraft:open_screen", fields, bytes([0x3C, 0x03, 0x02]) + CHEST_TITLE
    )


def test_container_set_content_is_every_slot_then_the_cursor() -> None:
    fields = {"window_id": 0, "state_id": 300, "slot_data": [None, STONE], "carried_item": None}
    data = bytes([0x12, 0x00, 0xAC, 0x02, 0x02, 0x00]) + STONE_BYTES + bytes([0x00])
    round_trip(CLIENTBOUND, "minecraft:container_set_content", fields, data)


def test_container_set_slot_is_the_window_the_state_a_short_slot_and_the_stack() -> None:
    fields = {"window_id": 1, "state_id": 5, "slot": 36, "slot_data": STONE}
    data = bytes([0x14, 0x01, 0x05, 0x00, 0x24]) + STONE_BYTES
    round_trip(CLIENTBOUND, "minecraft:container_set_slot", fields, data)


def test_container_set_data_is_the_window_and_two_shorts() -> None:
    fields = {"window_id": 2, "property": 3, "value": -1}
    data = bytes([0x13, 0x02, 0x00, 0x03, 0xFF, 0xFF])
    round_trip(CLIENTBOUND, "minecraft:container_set_data", fields, data)


@pytest.mark.parametrize(
    "direction", [CLIENTBOUND, SERVERBOUND], ids=["clientbound", "serverbound"]
)
def test_container_close_is_the_window(direction: Direction) -> None:
    packet_id = 0x11 if direction is CLIENTBOUND else 0x13
    round_trip(direction, "minecraft:container_close", {"window_id": 7}, bytes([packet_id, 0x07]))


def test_set_cursor_item_is_one_stack() -> None:
    round_trip(
        CLIENTBOUND, "minecraft:set_cursor_item", {"slot_data": STONE}, bytes([0x62]) + STONE_BYTES
    )


def test_set_player_inventory_is_an_inventory_index_and_a_stack() -> None:
    fields = {"slot": 40, "slot_data": None}
    round_trip(CLIENTBOUND, "minecraft:set_player_inventory", fields, bytes([0x6E, 0x28, 0x00]))


def test_container_click_carries_each_changed_slot_as_a_hashed_stack() -> None:
    fields = {
        "window_id": 0,
        "state_id": 2,
        "slot": 36,
        "button": 0,
        "mode": 1,
        "changed_slots": [{"slot": 36, "item": None}, {"slot": 9, "item": HASHED_STONE}],
        "carried_item": None,
    }
    data = (
        bytes([0x12, 0x00, 0x02])
        + struct.pack(">hb", 36, 0)
        + bytes([0x01, 0x02])
        + struct.pack(">h", 36)
        + bytes([0x00])
        + struct.pack(">h", 9)
        + HASHED_STONE_BYTES
        + bytes([0x00])
    )
    round_trip(SERVERBOUND, "minecraft:container_click", fields, data)


def test_container_click_carries_at_most_128_changed_slots() -> None:
    # ServerboundContainerClickPacket.MAX_SLOT_COUNT is 128 (ByteBufCodecs.map's limit).
    changed = struct.pack(">h", 0) + bytes([0x00])
    head = bytes([0x12, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    too_many = head + bytes([0x81, 0x01]) + changed * 129 + bytes([0x00])
    with pytest.raises(CodecError, match="exceeds max 128"):
        CODEC.decode(State.PLAY, SERVERBOUND, too_many)
