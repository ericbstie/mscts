"""Shared wire shapes of registry-aware types, from `ByteBufCodecs` and `StreamCodec` (26.3 javap).

The hex payloads are built by hand from those layouts (docs/research/2026-09-30-item-stacks.md),
not produced by the Codec.
"""

from typing import cast

import pytest
from support.wire import read_all, written

from mscts.codec.schema import IDENTIFIER, VAR_INT, SchemaError, WireType
from mscts.codec.shapes import (
    COMPOUND_TAG,
    ENUM,
    HOLDER_SET,
    NBT_TAG,
    REGISTRY_ID,
    UNIT,
    Either,
    FixedArray,
    Holder,
)
from mscts.codec.wire import Reader, WireError

# Registry ids and enums: plain VarInts with no offset (`registry`, `holderRegistry`, `idMapper`).


@pytest.mark.parametrize("wire_type", [REGISTRY_ID, ENUM], ids=["registry id", "enum"])
def test_a_registry_id_and_an_enum_are_a_plain_varint(wire_type: WireType[int]) -> None:
    assert read_all(wire_type, bytes.fromhex("c9 08")) == 1097
    assert written(wire_type, 1097) == bytes.fromhex("c9 08")
    assert read_all(wire_type, b"\x00") == 0


# Unit: `StreamCodec.unit`, no bytes at all; its value is None.


def test_unit_is_no_bytes_and_none() -> None:
    reader = Reader(b"\x01")
    assert UNIT.read(reader) is None
    assert reader.remaining == 1
    assert written(UNIT, None) == b""


@pytest.mark.parametrize("value", [0, False, {}, ""])
def test_unit_writes_only_none(value: object) -> None:
    with pytest.raises(WireError, match="expected None"):
        written(UNIT, value)


# NBT_TAG: a root tag of any type but END. The codec-derived stream codecs (`fromCodec*`) read it
# with `FriendlyByteBuf.readNbt`, which answers a TAG_End root with null and then throws.

NBT_STRING_TAG = bytes.fromhex("08 0002 6869")  # a String tag "hi": a text component
NBT_EMPTY_COMPOUND = bytes.fromhex("0a 00")


@pytest.mark.parametrize("tag", [NBT_STRING_TAG, NBT_EMPTY_COMPOUND], ids=["string", "compound"])
def test_nbt_tag_is_kept_as_its_exact_bytes(tag: bytes) -> None:
    assert read_all(NBT_TAG, tag) == tag
    assert written(NBT_TAG, tag) == tag


def test_nbt_tag_reads_one_tag_and_leaves_what_follows() -> None:
    reader = Reader(NBT_EMPTY_COMPOUND + b"\x07")
    assert NBT_TAG.read(reader) == NBT_EMPTY_COMPOUND
    assert reader.remaining == 1


def test_nbt_tag_refuses_a_tag_end_root_on_read() -> None:
    with pytest.raises(WireError, match="END"):
        read_all(NBT_TAG, b"\x00")


def test_nbt_tag_refuses_a_tag_end_root_on_write() -> None:
    with pytest.raises(WireError, match="END"):
        written(NBT_TAG, b"\x00")


def test_nbt_tag_refuses_no_bytes_and_a_truncated_tag() -> None:
    with pytest.raises(WireError):
        read_all(NBT_TAG, b"")
    with pytest.raises(WireError):
        read_all(NBT_TAG, bytes.fromhex("08 0002 68"))


def test_nbt_tag_writes_only_bytes() -> None:
    with pytest.raises(WireError, match="expected bytes"):
        written(NBT_TAG, "hi")


# COMPOUND_TAG: `ByteBufCodecs.COMPOUND_TAG`. An NBT root tag that must be a compound (type 10);
# any other type, END included, is a DecoderException.


def test_compound_tag_is_a_compound_root_kept_as_its_exact_bytes() -> None:
    tag = bytes.fromhex("0a 01 0002 6869 05 00")  # a compound with a Byte entry "hi" of 5
    assert read_all(COMPOUND_TAG, NBT_EMPTY_COMPOUND) == NBT_EMPTY_COMPOUND
    assert written(COMPOUND_TAG, NBT_EMPTY_COMPOUND) == NBT_EMPTY_COMPOUND
    assert read_all(COMPOUND_TAG, tag) == tag


@pytest.mark.parametrize(
    ("tag", "root_type"),
    [(NBT_STRING_TAG, 8), (b"\x00", 0), (bytes.fromhex("09 00 00 00 00 00"), 9)],
    ids=["string", "end", "list"],
)
def test_compound_tag_refuses_any_other_root_type(tag: bytes, root_type: int) -> None:
    with pytest.raises(WireError, match=rf"compound.*type {root_type}"):
        read_all(COMPOUND_TAG, tag)
    with pytest.raises(WireError, match=rf"compound.*type {root_type}"):
        written(COMPOUND_TAG, tag)


def test_compound_tag_refuses_no_bytes_and_what_is_not_bytes() -> None:
    with pytest.raises(WireError):
        read_all(COMPOUND_TAG, b"")
    with pytest.raises(WireError, match="expected bytes"):
        written(COMPOUND_TAG, "hi")


# FixedArray: `ByteBufCodecs.fixedSizeList(n)`. Exactly n elements and no count.

FOUR_INTS = FixedArray(VAR_INT, 4)


def test_a_fixed_array_is_its_elements_with_no_count() -> None:
    assert read_all(FOUR_INTS, bytes.fromhex("01 02 03 c9 08")) == [1, 2, 3, 1097]
    assert written(FOUR_INTS, [1, 2, 3, 1097]) == bytes.fromhex("01 02 03 c9 08")


def test_a_fixed_array_names_the_element_that_is_bad() -> None:
    with pytest.raises(WireError, match=r"^2: "):
        read_all(FOUR_INTS, bytes.fromhex("01 02"))
    with pytest.raises(WireError, match=r"^1: expected an int"):
        written(FOUR_INTS, [1, "x", 3, 4])


@pytest.mark.parametrize("value", [[1, 2, 3], [1, 2, 3, 4, 5], 5], ids=["short", "long", "no list"])
def test_a_fixed_array_writes_only_exactly_its_size(value: object) -> None:
    with pytest.raises(WireError, match="expected a list of 4"):
        written(FOUR_INTS, value)


@pytest.mark.parametrize("size", [-1, True, 1.5])
def test_a_fixed_array_needs_a_size_that_is_a_non_negative_int(size: object) -> None:
    with pytest.raises(SchemaError, match="size"):
        FixedArray(VAR_INT, cast("int", size))


# Holder: `ByteBufCodecs.holder`. A VarInt: 0 and then the value itself, else the registry id + 1.

HOLDER = Holder(VAR_INT)


@pytest.mark.parametrize(
    ("encoded", "value"),
    [("01", {"reference": 0}), ("2b", {"reference": 42}), ("00 07", {"direct": 7})],
    ids=["first entry", "entry 42", "the value itself"],
)
def test_a_holder_is_a_registry_id_plus_one_or_zero_and_the_value(
    encoded: str, value: dict[str, object]
) -> None:
    assert read_all(HOLDER, bytes.fromhex(encoded)) == value
    assert written(HOLDER, value) == bytes.fromhex(encoded)


def test_a_holder_refuses_a_negative_number() -> None:
    with pytest.raises(WireError, match=r"^holder id -1 is negative$"):
        read_all(HOLDER, bytes.fromhex("ffffffff0f"))


def test_a_holder_names_the_direct_value_when_it_is_bad() -> None:
    with pytest.raises(WireError, match=r"^direct: "):
        read_all(HOLDER, bytes.fromhex("00 80"))
    with pytest.raises(WireError, match=r"^direct: expected an int"):
        written(HOLDER, {"direct": "x"})


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({}, "exactly one of reference and direct"),
        ({"reference": 1, "direct": 1}, "exactly one of reference and direct"),
        ({"other": 1}, "exactly one of reference and direct"),
        ([("reference", 1)], "expected a mapping"),
        ({"reference": -1}, "negative"),
        ({"reference": True}, "expected an int"),
    ],
)
def test_a_holder_writes_only_one_of_a_reference_and_a_direct_value(
    value: object, message: str
) -> None:
    with pytest.raises(WireError, match=message):
        written(HOLDER, value)


# Either: `ByteBufCodecs.either`. A Bool, then the left type when true, else the right.

EITHER = Either("number", VAR_INT, "text", IDENTIFIER)


@pytest.mark.parametrize(
    ("encoded", "value"),
    [("01 05", {"number": 5}), ("00 03 61 3a 62", {"text": "a:b"})],
    ids=["left", "right"],
)
def test_an_either_is_a_bool_then_the_left_or_the_right_value(
    encoded: str, value: dict[str, object]
) -> None:
    assert read_all(EITHER, bytes.fromhex(encoded)) == value
    assert written(EITHER, value) == bytes.fromhex(encoded)


def test_an_either_refuses_a_bool_that_is_neither_zero_nor_one() -> None:
    with pytest.raises(WireError, match="invalid bool byte 0x02"):
        read_all(EITHER, bytes.fromhex("02 05"))


def test_an_either_names_the_side_whose_value_is_bad() -> None:
    with pytest.raises(WireError, match=r"^number: "):
        read_all(EITHER, bytes.fromhex("01 80"))
    with pytest.raises(WireError, match=r"^text: "):
        read_all(EITHER, bytes.fromhex("00"))
    with pytest.raises(WireError, match=r"^number: expected an int"):
        written(EITHER, {"number": "x"})


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({}, "exactly one of number and text"),
        ({"number": 1, "text": "a"}, "exactly one of number and text"),
        ({"other": 1}, "exactly one of number and text"),
        ([1], "expected a mapping"),
    ],
)
def test_an_either_writes_only_one_side(value: object, message: str) -> None:
    with pytest.raises(WireError, match=message):
        written(EITHER, value)


# Holder set: `ByteBufCodecs.holderSet`. A VarInt: 0 and then a tag's Identifier, else the
# number of ids + 1 and the ids.


@pytest.mark.parametrize(
    ("encoded", "value"),
    [
        ("00 03 61 3a 62", {"tag": "a:b"}),
        ("01", {"ids": []}),
        ("03 05 c9 08", {"ids": [5, 1097]}),
    ],
    ids=["tag", "no ids", "two ids"],
)
def test_a_holder_set_is_a_tag_or_a_list_of_registry_ids(
    encoded: str, value: dict[str, object]
) -> None:
    assert read_all(HOLDER_SET, bytes.fromhex(encoded)) == value
    assert written(HOLDER_SET, value) == bytes.fromhex(encoded)


def test_a_holder_set_refuses_a_negative_size() -> None:
    with pytest.raises(WireError, match="negative"):
        read_all(HOLDER_SET, bytes.fromhex("ffffffff0f"))


def test_a_holder_set_refuses_more_ids_than_there_are_bytes_left() -> None:
    with pytest.raises(WireError, match="exceeds"):
        read_all(HOLDER_SET, bytes.fromhex("06 00"))


def test_a_holder_set_names_the_part_that_is_bad() -> None:
    with pytest.raises(WireError, match=r"^tag: "):
        read_all(HOLDER_SET, bytes.fromhex("00"))
    with pytest.raises(WireError, match=r"^ids: 1: "):
        read_all(HOLDER_SET, bytes.fromhex("03 05 80"))
    with pytest.raises(WireError, match=r"^tag: "):
        written(HOLDER_SET, {"tag": 5})
    with pytest.raises(WireError, match=r"^ids: 0: expected an int"):
        written(HOLDER_SET, {"ids": ["x"]})


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({}, "exactly one of tag and ids"),
        ({"tag": "a:b", "ids": []}, "exactly one of tag and ids"),
        ([], "expected a mapping"),
        ({"ids": 5}, "expected a list"),
    ],
)
def test_a_holder_set_writes_only_a_tag_or_a_list_of_ids(value: object, message: str) -> None:
    with pytest.raises(WireError, match=message):
        written(HOLDER_SET, value)
