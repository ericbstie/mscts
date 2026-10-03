"""Where a packet holds entity ids: the paths the Codec names, found in the schemas by type.

A Comparison numbers entity ids by first appearance (#21) and refuses a Mask on one; both ask
the Codec where a packet's entity ids are, and never keep a list of packets of their own.
"""

from collections.abc import Iterator, Mapping

import pytest

from mscts.codec.entity_ids import EACH, Variant, entity_id_paths, inner_types
from mscts.codec.packets import Codec, Direction, State
from mscts.codec.schema import (
    ENTITY_ID,
    VAR_INT,
    EntityId,
    PrefixedArray,
    PrefixedOptional,
    Schema,
    Tagged,
    WireType,
)
from mscts.codec.schemas import configuration, handshake, login, play, status
from mscts.codec.shapes import Deferred, Either, FixedArray, Holder

CODEC = Codec.load("26.3")

VIBRATION = (
    Variant("type", "minecraft:vibration"),
    "options",
    "destination",
    Variant("type", "minecraft:entity"),
    "value",
    "entity_id",
)
"""From a particle to the entity a vibration travels to: the only entity id a particle has."""


def play_paths(name: str) -> tuple[tuple[object, ...], ...]:
    return CODEC.entity_id_paths(State.PLAY, Direction.CLIENTBOUND, name)


def test_a_packet_with_one_entity_id_names_its_field() -> None:
    assert play_paths("minecraft:login") == (("entity_id",),)
    assert play_paths("minecraft:sound_entity") == (("entity_id",),)
    assert play_paths("minecraft:block_destruction") == (("entity_id",),)


def test_a_list_of_entity_ids_is_each_of_its_elements() -> None:
    assert play_paths("minecraft:remove_entities") == (("entity_ids", EACH),)
    assert play_paths("minecraft:set_passengers") == (("vehicle",), ("passengers", EACH))


def test_entity_ids_that_can_be_none_are_named_too() -> None:
    assert play_paths("minecraft:set_entity_link") == (
        ("attached_entity_id",),
        ("holding_entity_id",),
    )
    assert play_paths("minecraft:damage_event") == (
        ("entity_id",),
        ("source_cause_id",),
        ("source_direct_id",),
    )


def test_a_particle_holds_an_entity_id_only_as_a_vibration_toward_an_entity() -> None:
    assert play_paths("minecraft:level_particles") == (("particle", *VIBRATION),)
    assert play_paths("minecraft:explode") == (
        ("explosion_particle", *VIBRATION),
        ("block_particles", EACH, "particle", *VIBRATION),
    )


def test_entity_metadata_holds_entity_ids_in_its_particle_values() -> None:
    assert play_paths("minecraft:set_entity_data") == (
        ("entity_id",),
        ("entries", EACH, Variant("serializer", "particle"), "value", *VIBRATION),
        ("entries", EACH, Variant("serializer", "particles"), "value", EACH, *VIBRATION),
    )


def test_a_packet_with_no_entity_id_or_no_schema_names_none() -> None:
    assert play_paths("minecraft:bundle_delimiter") == ()
    assert play_paths("minecraft:block_update") == ()
    assert (
        CODEC.entity_id_paths(State.STATUS, Direction.CLIENTBOUND, "minecraft:status_response")
        == ()
    )
    assert play_paths("minecraft:no_such_packet") == ()
    assert CODEC.entity_id_paths(State.PLAY, Direction.SERVERBOUND, "minecraft:login") == ()


def test_the_walk_goes_through_holders_eithers_arrays_and_optionals() -> None:
    wire_type = Schema(
        a=Holder(Schema(id=ENTITY_ID)),
        b=Either("left", ENTITY_ID, "right", VAR_INT),
        c=FixedArray(ENTITY_ID, 2),
        d=PrefixedOptional(PrefixedArray(ENTITY_ID)),
        e=VAR_INT,
    )
    assert entity_id_paths(wire_type) == (
        ("a", "direct", "id"),
        ("b", "left"),
        ("c", EACH),
        ("d", EACH),
    )


def test_a_tagged_value_holds_an_entity_id_only_in_the_variants_that_carry_one() -> None:
    wire_type = Tagged("kind", "payload", (("none", None), ("one", ENTITY_ID), ("n", VAR_INT)))
    assert entity_id_paths(wire_type) == ((Variant("kind", "one"), "payload"),)


def test_a_type_that_contains_itself_is_walked_once() -> None:
    tree = Schema(size=VAR_INT, children=PrefixedArray(Deferred(lambda: tree)))
    assert entity_id_paths(Schema(id=ENTITY_ID, tree=tree)) == (("id",),)


def test_a_type_that_contains_itself_and_an_entity_id_is_refused() -> None:
    node = Schema(id=ENTITY_ID, children=PrefixedArray(Deferred(lambda: node)))
    with pytest.raises(ValueError, match="contains itself and an entity id"):
        entity_id_paths(node)


# Every wire type a packet reaches is one the walk goes into, an EntityId, or one of these,
# which hold no entity id: so no packet's entity id escapes `Codec.entity_id_paths`. A new
# wire type fails the test below until it is walked or listed here, with the reason.
HOLDS_NO_ENTITY_ID: Mapping[str, str] = {
    "mscts.codec.schema._Bool": "a Boolean",
    "mscts.codec.schema._Byte": "a number",
    "mscts.codec.schema._Double": "a number",
    "mscts.codec.schema._Float": "a number",
    "mscts.codec.schema._Int": "a number",
    "mscts.codec.schema._Long": "a number",
    "mscts.codec.schema._Short": "a number",
    "mscts.codec.schema._UByte": "a number",
    "mscts.codec.schema._UShort": "a number",
    "mscts.codec.schema._VarInt": "a number",
    "mscts.codec.schema._VarLong": "a number",
    "mscts.codec.schema._Uuid": "a UUID (an entity's is renumbered by the Comparison's own rule)",
    "mscts.codec.schema._Rest": "bytes the codec does not read into fields",
    "mscts.codec.schema._Nbt": "NBT, kept as its bytes",
    "mscts.codec.schema._Position": "a block position",
    "mscts.codec.schema._LpVec3": "a velocity",
    "mscts.codec.schema.String": "a string",
    "mscts.codec.schema.Schema": "only a Schema with no fields reaches here",
    "mscts.codec.shapes.OrdinalEnum": "an enum ordinal",
    "mscts.codec.shapes._NbtTag": "NBT, kept as its bytes",
    "mscts.codec.shapes._CompoundTag": "NBT, kept as its bytes",
    "mscts.codec.shapes._SectionPosition": "a chunk section's position",
    "mscts.codec.shapes._HolderSet": "registry ids, or a tag's name",
    "mscts.codec.entity_data._ZeroIsNone": "a block state or a number",
    "mscts.codec.movement._MoveDelta": "a movement's numbers",
    "mscts.codec.movement._PositionPath": "a position's numbers",
    "mscts.codec.schemas.play.blocks._SectionBlock": "a block state and its position",
    "mscts.codec.schemas.play.chunks._ByteArray": "a light mask or a light array, as bytes",
    "mscts.codec.schemas.play.chunks._Buffer": "chunk sections: counts, block states and biomes",
    "mscts.codec.schemas.play.chunks._BlockEntity": "a block entity: position, type and NBT",
    "mscts.codec.schemas.play.commands.CommandNode": "the command tree",
    "mscts.codec.schemas.play.players._Actions": "which tab list actions a packet holds",
    "mscts.codec.schemas.play.advancements._Display": "text, an item stack and flags",
    "mscts.codec.equipment.EquipmentList": "equipment slots and item stacks",
    "mscts.codec.items._Slot": "an item stack: an item id, a count and data components",
    "mscts.codec.components.Patch": "data components: no layout in components.py is an EntityId",
}


_CLIENTBOUND, _SERVERBOUND = Direction.CLIENTBOUND, Direction.SERVERBOUND
_TABLES: tuple[tuple[State, Direction, Mapping[str, Schema]], ...] = (
    (State.HANDSHAKE, _SERVERBOUND, handshake.SERVERBOUND),
    (State.STATUS, _SERVERBOUND, status.SERVERBOUND),
    (State.STATUS, _CLIENTBOUND, status.CLIENTBOUND),
    (State.LOGIN, _SERVERBOUND, login.SERVERBOUND),
    (State.LOGIN, _CLIENTBOUND, login.CLIENTBOUND),
    (State.CONFIGURATION, _SERVERBOUND, configuration.SERVERBOUND),
    (State.CONFIGURATION, _CLIENTBOUND, configuration.CLIENTBOUND),
    (State.PLAY, _SERVERBOUND, play.SERVERBOUND),
    (State.PLAY, _CLIENTBOUND, play.CLIENTBOUND),
)


def _schemas() -> Iterator[tuple[State, Direction, str, Schema]]:
    for state, direction, schemas in _TABLES:
        for name, schema in schemas.items():
            yield state, direction, name, schema


def _leaves(wire_type: WireType[object], seen: set[int]) -> Iterator[WireType[object]]:
    """The wire types `wire_type` reaches that the walk goes no further into."""
    if id(wire_type) in seen:
        return
    seen.add(id(wire_type))
    inner = inner_types(wire_type)
    if not inner:
        yield wire_type
    for _, part in inner:
        yield from _leaves(part, seen)


def test_every_wire_type_a_packet_reaches_is_walked_or_holds_no_entity_id() -> None:
    unclassified: dict[str, str] = {}
    reached: set[str] = set()
    with_entity_ids: list[str] = []
    for state, direction, name, schema in _schemas():
        leaves = list(_leaves(schema, set()))
        for leaf in leaves:
            kind = f"{type(leaf).__module__}.{type(leaf).__qualname__}"
            reached.add(kind)
            if not isinstance(leaf, EntityId) and kind not in HOLDS_NO_ENTITY_ID:
                unclassified.setdefault(kind, f"{state} {direction} {name}")
        reaches_one = any(isinstance(leaf, EntityId) for leaf in leaves)
        assert bool(CODEC.entity_id_paths(state, direction, name)) == reaches_one, name
        if reaches_one:
            with_entity_ids.append(name)
    assert unclassified == {}
    assert set(HOLDS_NO_ENTITY_ID) - reached == set()  # no entry stays once its type goes
    assert "minecraft:set_entity_data" in with_entity_ids
