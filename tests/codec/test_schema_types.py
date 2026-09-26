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
