"""The entity packets of Target 26.3: each decodes into fields and re-encodes byte for byte.

Layouts come from the 26.3 jar (`javap` on each packet's `STREAM_CODEC`), which settled every
place the wiki (revision 3790659) is silent or differs; payloads are recorded from vanilla where
a probe could record one, else built by hand from those layouts.
"""

import uuid
from collections.abc import Mapping

import pytest

from mscts.codec.packets import Codec, Direction, State
from mscts.codec.schema import EntityId, PrefixedArray, PrefixedOptional, Schema, WireType
from mscts.codec.schemas import play

CODEC = Codec.load("26.3")
CLIENTBOUND = Direction.CLIENTBOUND


def round_trip(name: str, fields: Mapping[str, object], data: bytes) -> None:
    """`data` (id ‖ payload) decodes to `fields` and `fields` encode to `data`."""
    assert CODEC.packet_id(State.PLAY, CLIENTBOUND, name) == data[0]
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
    round_trip("minecraft:add_entity", fields, b"\x01" + bytes.fromhex(payload))


def test_add_entity_has_its_entity_id_as_an_entity_id() -> None:
    assert entity_id_paths(play_schema("minecraft:add_entity")) == ["entity_id"]


def test_remove_entities_decodes_and_re_encodes() -> None:
    # Recorded from vanilla: `kill` of the entity 17.
    round_trip("minecraft:remove_entities", {"entity_ids": [17]}, bytes.fromhex("4e0111"))
    # Built by hand: several ids (300 is a two-byte VarInt), and none.
    round_trip(
        "minecraft:remove_entities", {"entity_ids": [4, 300, 0]}, bytes.fromhex("4e0304ac0200")
    )
    round_trip("minecraft:remove_entities", {"entity_ids": []}, bytes.fromhex("4e00"))


def test_remove_entities_has_its_entity_ids_as_entity_ids() -> None:
    assert entity_id_paths(play_schema("minecraft:remove_entities")) == ["entity_ids[]"]


def test_bundle_delimiter_has_no_fields() -> None:
    round_trip("minecraft:bundle_delimiter", {}, b"\x00")
    assert entity_id_paths(play_schema("minecraft:bundle_delimiter")) == []
