"""The entity packets of Target 26.3: each decodes into fields and re-encodes byte for byte.

Layouts come from the 26.3 jar (`javap` on each packet's `STREAM_CODEC`), which settled every
place the wiki (revision 3790659) is silent or differs; payloads are recorded from vanilla where
a probe could record one, else built by hand from those layouts.
"""

import uuid
from collections.abc import Mapping

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, State
from mscts.codec.schema import EntityId, PrefixedArray, PrefixedOptional, Schema, WireType
from mscts.codec.schemas import play
from mscts.codec.wire import Writer

CODEC = Codec.load("26.3")
CLIENTBOUND = Direction.CLIENTBOUND


def round_trip(name: str, fields: Mapping[str, object], payload: str) -> None:
    """The packet `name`'s payload (hex, after the packet id) decodes to `fields` and back."""
    packet_id = Writer().var_int(CODEC.packet_id(State.PLAY, CLIENTBOUND, name)).to_bytes()
    data = packet_id + bytes.fromhex(payload)
    assert CODEC.encode(State.PLAY, CLIENTBOUND, name, fields) == data
    packet = CODEC.decode(State.PLAY, CLIENTBOUND, data)
    assert (packet.name, packet.fields) == (name, fields)


def entity_id_paths(wire_type: WireType[object], path: str = "") -> list[str]:
    """Where `wire_type` holds an entity id: the field paths, `[]` marking array elements.

    This is how a Comparison finds every entity id without a list of packets.
    """
    if isinstance(wire_type, EntityId):
        return [path]
    if isinstance(wire_type, Schema):
        return [
            found
            for name, field in wire_type.fields.items()
            for found in entity_id_paths(field, f"{path}.{name}" if path else name)
        ]
    if isinstance(wire_type, PrefixedArray | PrefixedOptional):
        suffix = "[]" if isinstance(wire_type, PrefixedArray) else ""
        return entity_id_paths(wire_type.element, path + suffix)
    return []


def play_schema(name: str) -> Schema:
    return play.CLIENTBOUND[name]


def test_login_has_its_entity_id_as_an_entity_id() -> None:
    assert entity_id_paths(play_schema("minecraft:login")) == ["entity_id"]


# Spawn and removal.

ZERO_VELOCITY = {"scale": 0, "x": 0, "y": 0, "z": 0}


def spawn(**changes: object) -> dict[str, object]:
    """An add_entity's fields: a pig at rest, with `changes`."""
    fields: dict[str, object] = {
        "entity_id": 2,
        "entity_uuid": uuid.UUID("10c1c8b8-101e-4956-aa23-ce633565a464"),
        "type": 101,
        "x": -5.5,
        "y": -60.0,
        "z": -5.5,
        "velocity": ZERO_VELOCITY,
        "pitch": 0,
        "yaw": 0,
        "head_yaw": 0,
        "data": 0,
    }
    return fields | changes


ADD_ENTITY = [
    # Each payload is recorded from vanilla 26.3, after its packet id.
    (
        "pig",
        "0210c1c8b8101e4956aa23ce633565a46465c016000000000000c04e000000000000c0160000000000000000000000",
        spawn(),
    ),
    (
        "arrow",
        "03e99e04ca25824f62ac42912a404baf9206c01e000000000000c04c800000000000c01e0000000000000000000000",
        spawn(
            entity_id=3,
            entity_uuid=uuid.UUID("e99e04ca-2582-4f62-ac42-912a404baf92"),
            type=6,
            x=-7.5,
            y=-57.0,
            z=-7.5,
        ),
    ),
    (
        "armor stand",
        "043244d81d71ae48ebbafa27b9c79b1e9a05c016000000000000c04e000000000000c0230000000000000000000000",
        spawn(
            entity_id=4,
            entity_uuid=uuid.UUID("3244d81d-71ae-48eb-bafa-27b9c79b1e9a"),
            type=5,
            z=-9.5,
        ),
    ),
    (
        "a turned pig, its head apart from its body",
        "0fac0f4ba497524c9aa7a3c308c80e118365c03a800000000000c04e00000000000040308000000000000000dd0200",
        spawn(
            entity_id=15,
            entity_uuid=uuid.UUID("ac0f4ba4-9752-4c9a-a7a3-c308c80e1183"),
            x=-26.5,
            z=16.5,
            yaw=-35,
            head_yaw=2,
        ),
    ),
    (
        "a dropped item in motion",
        "123ac722ef25bc40e0a9718272cc55722d48c01e000000000000c04e000000000000c01dfcdf3f56f82409f17543333100cb0000",
        spawn(
            entity_id=18,
            entity_uuid=uuid.UUID("3ac722ef-25bc-40e0-a971-8272cc55722d"),
            type=72,
            x=-7.5,
            z=-7.496945371325669,
            velocity={"scale": 1, "x": 15905, "y": 19660, "z": 15009},
            yaw=-53,
        ),
    ),
    # Built by hand: the pig again, with the object data of a two-byte VarInt.
    (
        "object data",
        "0210c1c8b8101e4956aa23ce633565a46465c016000000000000c04e000000000000c01600000000000000000000d209",
        spawn(data=1234),
    ),
    # Built by hand: the pig again, with an entity type past 127 (a two-byte VarInt).
    (
        "entity type past 127",
        "0210c1c8b8101e4956aa23ce633565a4649601c016000000000000c04e000000000000c0160000000000000000000000",
        spawn(type=150),
    ),
]


@pytest.mark.parametrize(
    ("payload", "fields"), [case[1:] for case in ADD_ENTITY], ids=[case[0] for case in ADD_ENTITY]
)
def test_add_entity_decodes_and_re_encodes(payload: str, fields: dict[str, object]) -> None:
    round_trip("minecraft:add_entity", fields, payload)


def test_add_entity_has_its_entity_id_as_an_entity_id() -> None:
    assert entity_id_paths(play_schema("minecraft:add_entity")) == ["entity_id"]


def test_remove_entities_decodes_and_re_encodes() -> None:
    # Recorded from vanilla: `kill` of the entity 17.
    round_trip("minecraft:remove_entities", {"entity_ids": [17]}, "01 11")
    # Built by hand: several ids (300 is a two-byte VarInt), and none.
    round_trip("minecraft:remove_entities", {"entity_ids": [4, 300, 0]}, "03 04 ac02 00")
    round_trip("minecraft:remove_entities", {"entity_ids": []}, "00")


def test_remove_entities_has_its_entity_ids_as_entity_ids() -> None:
    assert entity_id_paths(play_schema("minecraft:remove_entities")) == ["entity_ids[]"]


def test_bundle_delimiter_has_no_fields() -> None:
    round_trip("minecraft:bundle_delimiter", {}, "")
    assert entity_id_paths(play_schema("minecraft:bundle_delimiter")) == []


# Movement.

ZERO_DELTA = {"x": 0, "y": 0, "z": 0}


def test_move_entity_pos_decodes_and_re_encodes() -> None:
    # Both recorded from vanilla 26.3: a linear delta, then a stepped one.
    round_trip(
        "minecraft:move_entity_pos",
        {"entity_id": 2, "movement": {"on_ground": False, "linear": ZERO_DELTA}},
        "02 00 0000 0000 0000",
    )
    round_trip(
        "minecraft:move_entity_pos",
        {
            "entity_id": 2,
            "movement": {"on_ground": True, "stepped": [{"ticks": 3, **ZERO_DELTA}]},
        },
        "02 03 03 0000 0000 0000",
    )


def test_move_entity_pos_rot_decodes_and_re_encodes() -> None:
    # Recorded from vanilla 26.3. The yaw comes before the pitch on the wire.
    round_trip(
        "minecraft:move_entity_pos_rot",
        {
            "entity_id": 3,
            "movement": {"on_ground": False, "linear": {"x": 0, "y": -3891, "z": 0}},
            "yaw": 122,
            "pitch": -48,
        },
        "03 00 0000 f0cd 0000 7a d0",
    )
    round_trip(
        "minecraft:move_entity_pos_rot",
        {
            "entity_id": 2,
            "movement": {
                "on_ground": True,
                "stepped": [{"ticks": 3, "x": -914, "y": 0, "z": -479}],
            },
            "yaw": 98,
            "pitch": 0,
        },
        "02 03 03 fc6e 0000 fe21 62 00",
    )


def test_move_entity_rot_decodes_and_re_encodes() -> None:
    # Recorded from vanilla 26.3: on ground, yaw 96, pitch -29.
    round_trip(
        "minecraft:move_entity_rot",
        {"entity_id": 2, "on_ground": True, "yaw": 96, "pitch": -29},
        "02 01 60 e3",
    )
    round_trip(
        "minecraft:move_entity_rot",
        {"entity_id": 2, "on_ground": False, "yaw": 96, "pitch": 0},
        "02 00 60 00",
    )


def test_entity_position_sync_decodes_and_re_encodes() -> None:
    # Recorded from vanilla 26.3: a stepped path, and a linear one.
    round_trip(
        "minecraft:entity_position_sync",
        {
            "entity_id": 2,
            "position": {
                "stepped": [{"x": -5.5, "y": -60.0, "z": -5.5, "tick_offset": 3}],
            },
            "yaw": 0.0,
            "pitch": 0.0,
            "on_ground": True,
        },
        "02 01 01 c016000000000000 c04e000000000000 c016000000000000 03 00000000 00000000 01",
    )
    round_trip(
        "minecraft:entity_position_sync",
        {
            "entity_id": 18,
            "position": {"linear": {"x": -7.742291034212191, "y": -60.0, "z": -8.194195789661206}},
            "yaw": 286.6270751953125,
            "pitch": 0.0,
            "on_ground": True,
        },
        "12 00 c01ef81b241038b5 c04e000000000000 c020636da16b3b47 438f5044 00000000 01",
    )


def test_teleport_entity_decodes_and_re_encodes() -> None:
    # Built by hand from PositionMoveRotation: the entity 300, at (1.5, 64, -2.5) moving at
    # (0, -0.5, 0.25), yaw 90, pitch -45, with two relative flags, on the ground.
    round_trip(
        "minecraft:teleport_entity",
        {
            "entity_id": 300,
            "x": 1.5,
            "y": 64.0,
            "z": -2.5,
            "velocity_x": 0.0,
            "velocity_y": -0.5,
            "velocity_z": 0.25,
            "yaw": 90.0,
            "pitch": -45.0,
            "flags": 3,
            "on_ground": True,
        },
        "ac02 3ff8000000000000 4050000000000000 c004000000000000 "
        "0000000000000000 bfe0000000000000 3fd0000000000000 42b40000 c2340000 00000003 01",
    )


def test_set_entity_motion_decodes_and_re_encodes() -> None:
    # Recorded from vanilla 26.3: a pig's velocity, then a stopped arrow's.
    round_trip(
        "minecraft:set_entity_motion",
        {"entity_id": 2, "velocity": {"scale": 1, "x": 16383, "y": 15099, "z": 16383}},
        "02 f9ff7ffeebed",
    )
    round_trip(
        "minecraft:set_entity_motion",
        {"entity_id": 3, "velocity": {"scale": 0, "x": 0, "y": 0, "z": 0}},
        "03 00",
    )


def test_rotate_head_decodes_and_re_encodes() -> None:
    round_trip("minecraft:rotate_head", {"entity_id": 2, "head_yaw": 10}, "02 0a")  # recorded
    round_trip("minecraft:rotate_head", {"entity_id": 2, "head_yaw": -10}, "02 f6")


def test_move_minecart_along_track_decodes_and_re_encodes() -> None:
    # Built by hand from MinecartStep: the entity 7 and two steps, each a position, a velocity,
    # a yaw and a pitch (one byte each) and a weight.
    round_trip(
        "minecraft:move_minecart_along_track",
        {
            "entity_id": 7,
            "steps": [
                {
                    "x": 1.0,
                    "y": 2.0,
                    "z": 3.0,
                    "velocity_x": 0.5,
                    "velocity_y": 0.0,
                    "velocity_z": -0.5,
                    "yaw": 16,
                    "pitch": -16,
                    "weight": 1.0,
                },
                {
                    "x": 1.25,
                    "y": 2.0,
                    "z": 3.5,
                    "velocity_x": 0.0,
                    "velocity_y": 0.0,
                    "velocity_z": 0.0,
                    "yaw": 0,
                    "pitch": 0,
                    "weight": 0.5,
                },
            ],
        },
        "07 02 "
        "3ff0000000000000 4000000000000000 4008000000000000 "
        "3fe0000000000000 0000000000000000 bfe0000000000000 10 f0 3f800000 "
        "3ff4000000000000 4000000000000000 400c000000000000 "
        "0000000000000000 0000000000000000 0000000000000000 00 00 3f000000",
    )
    round_trip("minecraft:move_minecart_along_track", {"entity_id": 7, "steps": []}, "07 00")


@pytest.mark.parametrize(
    "name",
    [
        "move_entity_pos",
        "move_entity_pos_rot",
        "move_entity_rot",
        "entity_position_sync",
        "teleport_entity",
        "set_entity_motion",
        "rotate_head",
        "move_minecart_along_track",
    ],
)
def test_movement_packets_have_their_entity_id_as_an_entity_id(name: str) -> None:
    assert entity_id_paths(play_schema(f"minecraft:{name}")) == ["entity_id"]


# Metadata. The payloads are recorded from vanilla 26.3 (the probe's summons, data merges and
# damage); the entry a serializer id selects is pinned by javap in test_entity_data_entries.py.


def metadata(index: int, serializer: str, value: object) -> dict[str, object]:
    """One decoded entry of `set_entity_data`."""
    return {"index": index, "serializer": serializer, "value": value}


RECORDED_METADATA = [
    # A pig's health, 10.0.
    ("02 09 03 41200000 ff", 2, [metadata(9, "float", 10.0)]),
    ("04 09 03 41a00000 ff", 4, [metadata(9, "float", 20.0)]),
    ("02 09 03 41000000 ff", 2, [metadata(9, "float", 8.0)]),
    ("02 09 03 40c00000 ff", 2, [metadata(9, "float", 6.0)]),
    # An arrow's flag.
    ("03 0a 08 01 ff", 3, [metadata(10, "boolean", value=True)]),
    # A custom name (a String tag holding the JSON text "Bob"), then a boolean.
    (
        "02 02 06 01 08 0005 22 426f62 22 03 08 01 ff",
        2,
        [
            metadata(2, "optional_component", bytes.fromhex("08 0005 22 426f62 22")),
            metadata(3, "boolean", value=True),
        ],
    ),
    # A pig's health and sound variant.
    (
        "0f 09 03 41200000 14 1d 00 ff",
        15,
        [metadata(9, "float", 10.0), metadata(20, "pig_sound_variant", 0)],
    ),
    # An armor stand's head pose: three floats.
    (
        "04 10 09 41200000 41a00000 41f00000 ff",
        4,
        [metadata(16, "rotations", {"x": 10.0, "y": 20.0, "z": 30.0})],
    ),
    # A dying pig's pose (7) and health.
    (
        "02 06 14 07 09 03 00000000 ff",
        2,
        [metadata(6, "pose", 7), metadata(9, "float", 0.0)],
    ),
]


@pytest.mark.parametrize(("payload", "entity_id", "entries"), RECORDED_METADATA)
def test_set_entity_data_decodes_and_re_encodes(
    payload: str, entity_id: int, entries: list[dict[str, object]]
) -> None:
    round_trip("minecraft:set_entity_data", {"entity_id": entity_id, "entries": entries}, payload)


@pytest.mark.parametrize(
    "payload",
    [
        "11 08 07 03 37 00 00 ff",  # a dropped item: 3 of item 55
        "12 08 07 01 c9 08 00 00 ff",  # a dropped item: 1 of item 1097
        "1a 08 07 02 c9 08 00 00 ff",
    ],
)
def test_set_entity_data_with_an_item_stack_is_undecodable_until_the_item_codec_lands(
    payload: str,
) -> None:
    packet_id = CODEC.packet_id(State.PLAY, CLIENTBOUND, "minecraft:set_entity_data")
    data = Writer().var_int(packet_id).to_bytes() + bytes.fromhex(payload)
    with pytest.raises(CodecError, match=r"entries: 0: item_stack: item stack: needs #19$"):
        CODEC.decode(State.PLAY, CLIENTBOUND, data)


def test_set_entity_data_has_its_entity_id_as_an_entity_id() -> None:
    assert entity_id_paths(play_schema("minecraft:set_entity_data")) == ["entity_id"]


# Attributes and effects. The attribute and effect are registry ids (VarInts, not range checked).


def attribute(attribute_id: int, base: float, *modifiers: dict[str, object]) -> dict[str, object]:
    return {"attribute": attribute_id, "base": base, "modifiers": list(modifiers)}


def modifier(name: str, amount: float, operation: int) -> dict[str, object]:
    return {"id": name, "amount": amount, "operation": operation}


def test_update_attributes_decodes_and_re_encodes() -> None:
    # Recorded from vanilla 26.3: a player's three attributes.
    round_trip(
        "minecraft:update_attributes",
        {
            "entity_id": 1,
            "attributes": [
                attribute(13, 3.0),
                attribute(26, 0.10000000149011612),
                attribute(8, 4.5),
            ],
        },
        "01 03 0d 4008000000000000 00 1a 3fb99999a0000000 00 08 4012000000000000 00",
    )
    # Recorded: the same player in creative mode, where two attributes have a modifier.
    round_trip(
        "minecraft:update_attributes",
        {
            "entity_id": 1,
            "attributes": [
                attribute(13, 3.0, modifier("minecraft:creative_mode_entity_range", 2.0, 0)),
                attribute(8, 4.5, modifier("minecraft:creative_mode_block_range", 0.5, 0)),
            ],
        },
        "01 02 0d 4008000000000000 01 24 "
        "6d696e6563726166743a63726561746976655f6d6f64655f656e746974795f72616e6765 "
        "4000000000000000 00 "
        "08 4012000000000000 01 23 "
        "6d696e6563726166743a63726561746976655f6d6f64655f626c6f636b5f72616e6765 "
        "3fe0000000000000 00",
    )
    # Recorded: a pig's movement speed, and an armor stand's.
    round_trip(
        "minecraft:update_attributes",
        {"entity_id": 2, "attributes": [attribute(26, 0.25)]},
        "02 01 1a 3fd0000000000000 00",
    )
    round_trip(
        "minecraft:update_attributes",
        {"entity_id": 4, "attributes": [attribute(26, 0.7)]},
        "04 01 1a 3fe6666666666666 00",
    )


def test_update_attributes_decodes_modifiers_and_ids_of_two_bytes() -> None:
    # Built by hand: the entity 300, the attribute 200, and three modifiers: one that adds a
    # multiple of the base (operation 1), one of the total (2), and an operation past 127 (the
    # client maps it to 0, so the Codec keeps it as a VarInt).
    round_trip(
        "minecraft:update_attributes",
        {
            "entity_id": 300,
            "attributes": [
                attribute(
                    200,
                    -1.5,
                    modifier("a:b", 0.25, 1),
                    modifier("c:d", -0.5, 2),
                    modifier("e:f", 0.0, 300),
                )
            ],
        },
        "ac02 01 c801 bff8000000000000 03 "
        "03 613a62 3fd0000000000000 01 "
        "03 633a64 bfe0000000000000 02 "
        "03 653a66 0000000000000000 ac02",
    )
    round_trip("minecraft:update_attributes", {"entity_id": 1, "attributes": []}, "01 00")


def test_update_attributes_holds_at_most_128_attributes() -> None:
    one = "00 0000000000000000 00"  # the attribute 0, base 0.0, no modifiers
    packet_id = CODEC.packet_id(State.PLAY, CLIENTBOUND, "minecraft:update_attributes")
    fields = {"entity_id": 1, "attributes": [attribute(0, 0.0)] * 128}
    data = Writer().var_int(packet_id).to_bytes() + bytes.fromhex(f"01 80 01 {one * 128}")
    assert CODEC.encode(State.PLAY, CLIENTBOUND, "minecraft:update_attributes", fields) == data
    assert CODEC.decode(State.PLAY, CLIENTBOUND, data).fields == fields
    too_many = {"entity_id": 1, "attributes": [attribute(0, 0.0)] * 129}
    with pytest.raises(CodecError, match=r"attributes: array length 129 exceeds max 128"):
        CODEC.encode(State.PLAY, CLIENTBOUND, "minecraft:update_attributes", too_many)
    data = Writer().var_int(packet_id).to_bytes() + bytes.fromhex(f"01 81 01 {one * 129}")
    with pytest.raises(CodecError, match=r"attributes: array length 129 exceeds max 128"):
        CODEC.decode(State.PLAY, CLIENTBOUND, data)


def test_update_mob_effect_decodes_and_re_encodes() -> None:
    # Built by hand: the entity 300 has effect 1 at amplifier 1 for 600 ticks, with the flags
    # for a visible effect and its icon; then an infinite effect (duration -1) of amplifier 200.
    round_trip(
        "minecraft:update_mob_effect",
        {"entity_id": 300, "effect": 1, "amplifier": 1, "duration": 600, "flags": 6},
        "ac02 01 01 d804 06",
    )
    round_trip(
        "minecraft:update_mob_effect",
        {"entity_id": 2, "effect": 300, "amplifier": 200, "duration": -1, "flags": -128},
        "02 ac02 c801 ffffffff0f 80",
    )


def test_remove_mob_effect_decodes_and_re_encodes() -> None:
    round_trip("minecraft:remove_mob_effect", {"entity_id": 2, "effect": 16}, "02 10")
    round_trip("minecraft:remove_mob_effect", {"entity_id": 300, "effect": 300}, "ac02 ac02")


@pytest.mark.parametrize("name", ["update_attributes", "update_mob_effect", "remove_mob_effect"])
def test_attribute_and_effect_packets_have_their_entity_id_as_an_entity_id(name: str) -> None:
    assert entity_id_paths(play_schema(f"minecraft:{name}")) == ["entity_id"]
