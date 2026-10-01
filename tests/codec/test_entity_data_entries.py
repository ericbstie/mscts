"""Entity metadata entries: the serializer table of 26.3, in registration order.

Pinned with `javap` on `EntityDataSerializers` (the static initializer registers the serializers
in this order, and the registration order is the id). The hex payloads are built by hand from each
serializer's `StreamCodec` layout, not produced by the Codec.
"""

import uuid

import pytest
from support.items import stack

from mscts.codec.entity_data import ENTITY_DATA, SERIALIZERS
from mscts.codec.schema import WireType
from mscts.codec.wire import Reader, WireError, Writer

SERIALIZER_NAMES = (
    "byte",
    "int",
    "long",
    "float",
    "string",
    "component",
    "optional_component",
    "item_stack",
    "boolean",
    "rotations",
    "block_pos",
    "optional_block_pos",
    "direction",
    "optional_living_entity_reference",
    "block_state",
    "optional_block_state",
    "particle",
    "particles",
    "villager_data",
    "optional_unsigned_int",
    "pose",
    "cat_variant",
    "cat_sound_variant",
    "cow_variant",
    "cow_sound_variant",
    "wolf_variant",
    "wolf_sound_variant",
    "frog_variant",
    "pig_variant",
    "pig_sound_variant",
    "chicken_variant",
    "chicken_sound_variant",
    "zombie_nautilus_variant",
    "optional_global_pos",
    "painting_variant",
    "sniffer_state",
    "armadillo_state",
    "copper_golem_state",
    "weathering_copper_state",
    "vector3",
    "quaternion",
    "resolvable_profile",
    "humanoid_arm",
    "dye_color",
)

SAMPLE_UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")
UUID_HEX = "12345678 12345678 12345678 12345678"
STRING_TAG = bytes.fromhex("08 0003 616263")  # the NBT String tag "abc"
POSITION = {"x": 1, "y": 2, "z": 3}
POSITION_HEX = "0000004000003002"
DRAGON_BREATH = {"type": "minecraft:dragon_breath", "options": {"power": 1.0}}
ANGRY_VILLAGER = {"type": "minecraft:angry_villager", "options": None}
VECTOR = {"x": 1.0, "y": 2.0, "z": 3.0}
VECTOR_HEX = "3f800000 40000000 40400000"
PARTIAL_PROFILE = f"00 00 01 {UUID_HEX} 00  00 00 00 00"

# Each sample: the serializer, its value's hex, the decoded value.
SAMPLES: list[tuple[str, str, object]] = [
    ("byte", "ff", -1),
    ("int", "ac02", 300),
    ("long", "ffffffffffffffffff01", -1),
    ("float", "41200000", 10.0),
    ("string", "03 616263", "abc"),
    ("component", "08 0003 616263", STRING_TAG),
    ("optional_component", "00", None),
    ("optional_component", "01 08 0003 616263", STRING_TAG),
    ("item_stack", "00", None),
    ("item_stack", "03 37 00 00", stack(3, 55)),
    ("item_stack", "01 37 01 00 03 07", stack(1, 55, damage=7)),
    ("boolean", "01", True),
    ("rotations", VECTOR_HEX, VECTOR),
    ("block_pos", POSITION_HEX, POSITION),
    ("optional_block_pos", "00", None),
    ("optional_block_pos", f"01 {POSITION_HEX}", POSITION),
    ("direction", "03", 3),
    ("optional_living_entity_reference", "00", None),
    ("optional_living_entity_reference", f"01 {UUID_HEX}", SAMPLE_UUID),
    ("block_state", "ac02", 300),
    ("optional_block_state", "00", None),
    ("optional_block_state", "2a", 42),
    ("particle", "0f 3f800000", DRAGON_BREATH),
    ("particles", "02 00 0f 3f800000", [ANGRY_VILLAGER, DRAGON_BREATH]),
    ("villager_data", "02 05 03", {"type": 2, "profession": 5, "level": 3}),
    ("optional_unsigned_int", "00", None),
    ("optional_unsigned_int", "2b", 42),
    ("pose", "07", 7),
    ("cat_variant", "2a", 42),
    ("cat_sound_variant", "2a", 42),
    ("cow_variant", "2a", 42),
    ("cow_sound_variant", "2a", 42),
    ("wolf_variant", "2a", 42),
    ("wolf_sound_variant", "2a", 42),
    ("frog_variant", "2a", 42),
    ("pig_variant", "2a", 42),
    ("pig_sound_variant", "2a", 42),
    ("chicken_variant", "2a", 42),
    ("chicken_sound_variant", "2a", 42),
    ("zombie_nautilus_variant", "2a", 42),
    ("optional_global_pos", "00", None),
    (
        "optional_global_pos",
        f"01 136d696e6563726166743a6f766572776f726c64 {POSITION_HEX}",
        {"dimension": "minecraft:overworld", "pos": POSITION},
    ),
    ("painting_variant", "01", {"reference": 0}),
    ("sniffer_state", "02", 2),
    ("armadillo_state", "01", 1),
    ("copper_golem_state", "03", 3),
    ("weathering_copper_state", "02", 2),
    ("vector3", VECTOR_HEX, VECTOR),
    ("quaternion", f"{VECTOR_HEX} 40800000", {"x": 1.0, "y": 2.0, "z": 3.0, "w": 4.0}),
    (
        "resolvable_profile",
        PARTIAL_PROFILE,
        {
            "profile": {"partial": {"name": None, "id": SAMPLE_UUID, "properties": []}},
            "skin_patch": {"body": None, "cape": None, "elytra": None, "slim": None},
        },
    ),
    ("humanoid_arm", "01", 1),
    ("dye_color", "0f", 15),
]


def written[T](wire_type: WireType[T], value: object) -> bytes:
    writer = Writer()
    wire_type.write(writer, value)
    return writer.to_bytes()


def read_all[T](wire_type: WireType[T], data: bytes) -> T:
    reader = Reader(data)
    value = wire_type.read(reader)
    reader.expect_end()
    return value


def entry(index: int, serializer: str, value: object) -> dict[str, object]:
    return {"index": index, "serializer": serializer, "value": value}


def test_the_serializers_are_those_of_26_3_in_registration_order() -> None:
    assert len(SERIALIZER_NAMES) == 44
    assert SERIALIZERS.names == SERIALIZER_NAMES


def test_every_serializer_has_a_sample() -> None:
    assert {name for name, _, _ in SAMPLES} == set(SERIALIZER_NAMES)


@pytest.mark.parametrize(("name", "value_hex", "value"), SAMPLES)
def test_each_serializer_decodes_its_value_and_encodes_the_same_bytes(
    name: str, value_hex: str, value: object
) -> None:
    serializer_id = SERIALIZER_NAMES.index(name)
    index = serializer_id + 3
    encoded = bytes.fromhex(f"{index:02x} {serializer_id:02x} {value_hex} ff")
    assert read_all(ENTITY_DATA, encoded) == [entry(index, name, value)]
    assert written(ENTITY_DATA, [entry(index, name, value)]) == encoded


# The serializers whose value is one VarInt: an id of a registry, an enum or the block states.
VAR_INT_SERIALIZERS = (
    "int",
    "direction",
    "block_state",
    "pose",
    "cat_variant",
    "cat_sound_variant",
    "cow_variant",
    "cow_sound_variant",
    "wolf_variant",
    "wolf_sound_variant",
    "frog_variant",
    "pig_variant",
    "pig_sound_variant",
    "chicken_variant",
    "chicken_sound_variant",
    "zombie_nautilus_variant",
    "sniffer_state",
    "armadillo_state",
    "copper_golem_state",
    "weathering_copper_state",
    "humanoid_arm",
    "dye_color",
)


@pytest.mark.parametrize("name", VAR_INT_SERIALIZERS)
def test_an_id_serializer_is_a_var_int_that_is_not_range_checked(name: str) -> None:
    encoded = bytes.fromhex(f"03 {SERIALIZER_NAMES.index(name):02x} ac02 ff")
    assert read_all(ENTITY_DATA, encoded) == [entry(3, name, 300)]
    assert written(ENTITY_DATA, [entry(3, name, 300)]) == encoded


def test_the_string_serializer_holds_at_most_32767_characters() -> None:
    written(ENTITY_DATA, [entry(0, "string", "a" * 32767)])
    with pytest.raises(WireError, match=r"^0: string: .*max length 32767 "):
        written(ENTITY_DATA, [entry(0, "string", "a" * 32768)])


def test_an_item_stack_the_codec_cannot_read_is_refused_naming_the_entry_and_the_component() -> (
    None
):
    # One of item 55 with one added component, of type 122: there are 122 types (0 to 121).
    error = r"^0: item_stack: components: added: 0: unknown data component type id 122$"
    with pytest.raises(WireError, match=error):
        read_all(ENTITY_DATA, bytes.fromhex("08 07 01 37 01 00 7a ff"))
    with pytest.raises(WireError, match=r"^0: item_stack: count: 0 is not positive"):
        written(ENTITY_DATA, [entry(8, "item_stack", stack(0, 55))])


def test_no_entries_is_just_the_terminator() -> None:
    assert read_all(ENTITY_DATA, b"\xff") == []
    assert written(ENTITY_DATA, []) == b"\xff"


def test_entries_keep_their_order() -> None:
    encoded = bytes.fromhex("00 00 41  01 01 2a  ff")
    value = [entry(0, "byte", 65), entry(1, "int", 42)]
    assert read_all(ENTITY_DATA, encoded) == value
    assert written(ENTITY_DATA, value) == encoded


def test_the_highest_index_is_254_since_255_ends_the_list() -> None:
    encoded = bytes.fromhex("fe 00 01 ff")
    assert read_all(ENTITY_DATA, encoded) == [entry(254, "byte", 1)]
    assert written(ENTITY_DATA, [entry(254, "byte", 1)]) == encoded


def test_entries_without_a_terminator_are_refused() -> None:
    with pytest.raises(WireError, match=r"^entries end without the 0xff terminator$"):
        read_all(ENTITY_DATA, bytes.fromhex("00 00 01"))
    with pytest.raises(WireError, match=r"^entries end without the 0xff terminator$"):
        read_all(ENTITY_DATA, b"")


@pytest.mark.parametrize(
    ("encoded", "error"),
    [
        ("00 2c", r"^0: unknown serializer id 44$"),
        ("00 00 01  01 2c", r"^1: unknown serializer id 44$"),
        ("00 03 4120", r"^0: float: "),
        ("00 08 02", r"^0: boolean: invalid bool byte 0x02$"),
    ],
)
def test_bad_entries_are_refused_naming_the_entry(encoded: str, error: str) -> None:
    with pytest.raises(WireError, match=error):
        read_all(ENTITY_DATA, bytes.fromhex(encoded))


@pytest.mark.parametrize(
    ("value", "error"),
    [
        (entry(255, "byte", 0), r"^0: index 255 is not in 0..254$"),
        (entry(-1, "byte", 0), r"^0: index -1 is not in 0..254$"),
        ({"index": True, "serializer": "byte", "value": 0}, r"^0: index: expected an int"),
        (entry(0, "nope", 0), r"^0: unknown serializer 'nope'$"),
        (entry(0, "float", 1), r"^0: float: expected a float"),
        ({"index": 0, "serializer": "byte"}, r"^0: missing key value$"),
        ({"index": 0, "serializer": "byte", "value": 0, "x": 1}, r"^0: unexpected key x$"),
        ({"serializer": "byte", "y": 1, "x": 2}, r"^0: missing key index; missing key value; "),
        ({"index": 0, "serializer": "byte", "value": 0, "y": 1, "x": 2}, r"; unexpected key y$"),
        ({"index": 0, "x": 1}, r"^0: missing key serializer; missing key value; unexpected key x$"),
        ("byte", r"^0: expected a mapping"),
    ],
)
def test_bad_entries_are_refused_when_writing(value: object, error: str) -> None:
    with pytest.raises(WireError, match=error):
        written(ENTITY_DATA, [value])


def test_entries_are_written_from_a_list_or_tuple_only() -> None:
    assert written(ENTITY_DATA, (entry(0, "byte", 1),)) == bytes.fromhex("00 00 01 ff")
    with pytest.raises(WireError, match=r"^expected a list or tuple"):
        written(ENTITY_DATA, {"index": 0})
