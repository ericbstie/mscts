"""Shared wire shapes of registry-aware types, from `ByteBufCodecs` and `StreamCodec` (26.3 javap).

The hex payloads are built by hand from those layouts (docs/research/2026-09-30-item-stacks.md),
not produced by the Codec.
"""

import pytest
from support.wire import read_all, written

from mscts.codec.schema import WireType
from mscts.codec.shapes import ENUM, NBT_TAG, REGISTRY_ID, UNIT
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
