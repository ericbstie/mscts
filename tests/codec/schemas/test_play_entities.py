"""The entity packets of Target 26.3: each decodes into fields and re-encodes byte for byte.

Layouts come from the 26.3 jar (`javap` on each packet's `STREAM_CODEC`), which settled every
place the wiki (revision 3790659) is silent or differs; payloads are recorded from vanilla where
a probe could record one, else built by hand from those layouts.
"""

from collections.abc import Mapping

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
