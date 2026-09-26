"""The schema's field types: each reads what it writes, and refuses what it cannot encode."""

import uuid
from typing import cast

import pytest

from mscts.codec.schema import (
    BOOL,
    BYTE,
    DOUBLE,
    FLOAT,
    IDENTIFIER,
    INT,
    NBT,
    POSITION,
    REST,
    UUID,
    VAR_INT,
    PrefixedArray,
    PrefixedOptional,
    Schema,
    SchemaError,
    String,
    WireType,
)
from mscts.codec.wire import Reader, WireError, Writer

SAMPLE_UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def written[T](wire_type: WireType[T], value: object) -> bytes:
    writer = Writer()
    wire_type.write(writer, value)
    return writer.to_bytes()


def read_all[T](wire_type: WireType[T], data: bytes) -> T:
    reader = Reader(data)
    value = wire_type.read(reader)
    reader.expect_end()
    return value


@pytest.mark.parametrize(("value", "encoded"), [(True, "01"), (False, "00")])
def test_bool_round_trips(*, value: bool, encoded: str) -> None:
    assert written(BOOL, value) == bytes.fromhex(encoded)
    assert read_all(BOOL, bytes.fromhex(encoded)) is value


# The mirror of "ints reject bool" (audit L4): a bool field takes only a bool.
@pytest.mark.parametrize("value", [1, 0, "", "true", None])
def test_bool_refuses_a_value_that_is_not_a_bool(value: object) -> None:
    with pytest.raises(WireError, match="expected a bool"):
        written(BOOL, value)


@pytest.mark.parametrize(
    ("wire_type", "value", "encoded"),
    [
        (BYTE, -1, "ff"),
        (INT, -2, "fffffffe"),
        (FLOAT, -90.5, "c2b50000"),
        (DOUBLE, 6.5, "401a000000000000"),
        (REST, b"\x00\x01", "0001"),
        (REST, b"", ""),
    ],
)
def test_fixed_size_types_round_trip(
    wire_type: WireType[object], value: object, encoded: str
) -> None:
    assert written(wire_type, value) == bytes.fromhex(encoded)
    assert read_all(wire_type, bytes.fromhex(encoded)) == value


@pytest.mark.parametrize(
    ("wire_type", "value", "error"),
    [
        (BYTE, True, "expected an int"),
        (INT, 1.0, "expected an int"),
        (INT, 2**31, "out of range"),
        (FLOAT, 1, "expected a float"),
        (FLOAT, 0.1, "is not exactly a Float"),
        (DOUBLE, True, "expected a float"),
        (REST, bytearray(b"x"), "expected bytes"),
        (REST, "x", "expected bytes"),
    ],
)
def test_fixed_size_types_refuse_what_they_cannot_encode(
    wire_type: WireType[object], value: object, error: str
) -> None:
    with pytest.raises(WireError, match=error):
        written(wire_type, value)


def test_uuid_round_trips() -> None:
    assert written(UUID, SAMPLE_UUID) == SAMPLE_UUID.bytes
    assert read_all(UUID, SAMPLE_UUID.bytes) == SAMPLE_UUID


@pytest.mark.parametrize("value", [str(SAMPLE_UUID), SAMPLE_UUID.bytes, SAMPLE_UUID.int])
def test_uuid_refuses_a_value_that_is_not_a_uuid(value: object) -> None:
    with pytest.raises(WireError, match="expected a UUID"):
        written(UUID, value)


# Prefixed Array of X: a VarInt length, then that many X (wiki Data types).

IDS = PrefixedArray(VAR_INT)
PACKS = PrefixedArray(Schema(namespace=String(8), id=String(8)))


def test_prefixed_array_round_trips() -> None:
    assert written(IDS, [1, 300]) == bytes.fromhex("02 01 ac02")
    assert read_all(IDS, bytes.fromhex("02 01 ac02")) == [1, 300]
    assert written(IDS, ()) == bytes.fromhex("00")
    assert read_all(IDS, bytes.fromhex("00")) == []


def test_prefixed_array_nests_a_schema() -> None:
    packs = [{"namespace": "minecraft", "id": "core"}]
    with pytest.raises(WireError, match="0: namespace: string exceeds max length 8"):
        written(PACKS, packs)
    packs = [{"namespace": "mc", "id": "core"}]
    data = written(PACKS, packs)
    assert data == bytes.fromhex("01 02 6d63 04 636f7265")
    assert read_all(PACKS, data) == packs


def test_prefixed_array_errors_name_the_element_index() -> None:
    with pytest.raises(WireError, match="1: VarInt truncated"):
        read_all(IDS, bytes.fromhex("02 01 80"))
    with pytest.raises(WireError, match="1: expected an int, got str"):
        written(IDS, [1, "2"])


def test_prefixed_array_refuses_a_negative_length() -> None:
    with pytest.raises(WireError, match="array length -1 is negative"):
        read_all(IDS, bytes.fromhex("ffffffff0f"))


def test_prefixed_array_refuses_more_elements_than_bytes_left() -> None:
    # No element type takes less than a byte, so this bounds the work a length can ask for.
    with pytest.raises(WireError, match="array length 2147483647 exceeds the 1 byte"):
        read_all(IDS, bytes.fromhex("ffffffff07 01"))


def test_prefixed_array_enforces_its_max_length() -> None:
    capped = PrefixedArray(VAR_INT, max_length=2)
    assert read_all(capped, bytes.fromhex("02 01 02")) == [1, 2]
    with pytest.raises(WireError, match="array length 3 exceeds max 2"):
        read_all(capped, bytes.fromhex("03 01 02 03"))
    with pytest.raises(WireError, match="array length 3 exceeds max 2"):
        written(capped, [1, 2, 3])


@pytest.mark.parametrize("value", ["12", b"\x01", {1: 2}, 1, None])
def test_prefixed_array_writes_only_a_list_or_tuple(value: object) -> None:
    with pytest.raises(WireError, match="expected a list or tuple"):
        written(IDS, value)


@pytest.mark.parametrize("max_length", [-1, True, 1.5])
def test_prefixed_array_refuses_a_bad_max_length(max_length: object) -> None:
    with pytest.raises(SchemaError, match="PrefixedArray max_length"):
        PrefixedArray(VAR_INT, max_length=cast("int", max_length))


# Prefixed Optional X: a Boolean, then X if it is true (wiki Data types).

MAYBE_ID = PrefixedOptional(VAR_INT)


def test_prefixed_optional_round_trips() -> None:
    assert written(MAYBE_ID, None) == bytes.fromhex("00")
    assert read_all(MAYBE_ID, bytes.fromhex("00")) is None
    assert written(MAYBE_ID, 7) == bytes.fromhex("01 07")
    assert read_all(MAYBE_ID, bytes.fromhex("01 07")) == 7


def test_prefixed_optional_reads_its_flag_strictly() -> None:
    with pytest.raises(WireError, match="invalid bool byte 0x02"):
        read_all(MAYBE_ID, bytes.fromhex("02 07"))


def test_prefixed_optional_passes_on_its_element_errors() -> None:
    with pytest.raises(WireError, match="expected an int"):
        written(MAYBE_ID, "7")


def test_identifier_is_a_string_of_at_most_32767() -> None:
    assert read_all(IDENTIFIER, bytes.fromhex("0f") + b"minecraft:brand") == "minecraft:brand"
    assert written(IDENTIFIER, "x" * 32767)[:3] == bytes.fromhex("ffff01")


# NBT, in its network form (an unnamed root: a tag type byte, then its payload). Its value
# is the tag's exact bytes, validated structurally (wiki NBT; vanilla NbtIo, javap).


def compound(*entries: bytes) -> bytes:
    """A TAG_Compound payload of already-encoded named entries, then TAG_End."""
    return b"".join(entries) + b"\x00"


def named(tag_type: int, name: str, payload: bytes) -> bytes:
    return bytes([tag_type]) + len(name).to_bytes(2, "big") + name.encode() + payload


NBT_SAMPLES = [
    "00",  # TAG_End: no tag at all
    "08 0005 6d73637473",  # a string root: "mscts", as a plain text component is sent
    "0a" + compound(named(1, "b", b"\x01"), named(8, "text", b"\x00\x02hi")).hex(),
    "0a"
    + compound(
        named(9, "list", bytes([3]) + (2).to_bytes(4, "big") + bytes(8)),  # 2 Ints
        named(9, "empty", bytes([0]) + bytes(4)),  # an empty list may have type End
        named(7, "bytes", (3).to_bytes(4, "big") + b"abc"),
        named(11, "ints", (1).to_bytes(4, "big") + bytes(4)),
        named(12, "longs", (1).to_bytes(4, "big") + bytes(8)),
        named(10, "nested", compound(named(6, "d", bytes(8)), named(4, "l", bytes(8)))),
        named(2, "s", bytes(2)),
        named(5, "f", bytes(4)),
    ).hex(),
]


@pytest.mark.parametrize("hex_tag", NBT_SAMPLES)
def test_nbt_reads_one_tag_as_its_exact_bytes(hex_tag: str) -> None:
    tag = bytes.fromhex(hex_tag)
    reader = Reader(tag + b"\xff")  # a byte after the tag is left for the next field
    assert NBT.read(reader) == tag
    assert reader.remaining == 1
    assert written(NBT, tag) == tag


@pytest.mark.parametrize(
    ("hex_tag", "error"),
    [
        ("0d", "NBT: invalid tag type 13"),
        ("0a" + named(13, "x", b"").hex() + "00", "NBT: invalid tag type 13"),
        ("09 00 00000001", "NBT: a list of 1 element\\(s\\) has no element type"),
        ("09 01 ffffffff", "NBT: negative length -1"),
        ("07 ffffffff", "NBT: negative length -1"),
        ("08 0005 6d73", "NBT: 5 byte\\(s\\) truncated"),
        ("0a 01 0001 62", r"NBT: 1 byte\(s\) truncated"),
        ("0a", r"NBT: 1 byte\(s\) truncated"),  # a compound without its TAG_End
    ],
)
def test_nbt_refuses_a_malformed_tag(hex_tag: str, error: str) -> None:
    with pytest.raises(WireError, match=error):
        NBT.read(Reader(bytes.fromhex(hex_tag)))


def test_nbt_nests_at_most_512_deep_as_vanilla_does() -> None:
    def lists(depth: int) -> bytes:  # `depth` lists, each holding the next one
        return b"\x09" + b"\x09\x00\x00\x00\x01" * (depth - 1) + b"\x00" + bytes(4)

    assert NBT.read(Reader(lists(512))) == lists(512)
    with pytest.raises(WireError, match="NBT: nested deeper than 512"):
        NBT.read(Reader(lists(513)))


@pytest.mark.parametrize("value", ["0a00", bytearray(b"\x00"), None])
def test_nbt_writes_only_bytes(value: object) -> None:
    with pytest.raises(WireError, match="expected bytes"):
        written(NBT, value)


@pytest.mark.parametrize("value", [b"\x0d", b"\x00\x00", b""])
def test_nbt_writes_only_exactly_one_well_formed_tag(value: bytes) -> None:
    with pytest.raises(WireError, match="NBT:"):
        written(NBT, value)


# Position: x (26 bits), z (26), y (12), signed, in one Long (wiki Data types).

WIKI_POSITION = {"x": 18357644, "y": 831, "z": -20882616}
WIKI_POSITION_BITS = "0100011000000111011000110010110000010101101101001000001100111111"


def test_position_matches_the_wiki_example() -> None:
    encoded = int(WIKI_POSITION_BITS, 2).to_bytes(8, "big")
    assert read_all(POSITION, encoded) == WIKI_POSITION
    assert written(POSITION, WIKI_POSITION) == encoded


@pytest.mark.parametrize(
    "position",
    [
        {"x": -(2**25), "y": -(2**11), "z": -(2**25)},
        {"x": 2**25 - 1, "y": 2**11 - 1, "z": 2**25 - 1},
        {"x": 0, "y": -1, "z": 0},
    ],
)
def test_position_round_trips_its_extremes(position: dict[str, int]) -> None:
    assert read_all(POSITION, written(POSITION, position)) == position


@pytest.mark.parametrize(
    ("position", "error"),
    [
        ({"x": 2**25, "y": 0, "z": 0}, "x: 33554432 out of range"),
        ({"x": 0, "y": -(2**11) - 1, "z": 0}, "y: -2049 out of range"),
        ({"x": 0, "y": 0, "z": True}, "z: expected an int"),
        ({"x": 0, "y": 0}, "missing field\\(s\\) z"),
        ([0, 0, 0], "expected a mapping"),
    ],
)
def test_position_refuses_what_it_cannot_encode(position: object, error: str) -> None:
    with pytest.raises(WireError, match=error):
        written(POSITION, position)
