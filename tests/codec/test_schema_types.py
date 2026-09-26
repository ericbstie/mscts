"""The schema's field types: each reads what it writes, and refuses what it cannot encode."""

import uuid

import pytest

from mscts.codec.schema import BOOL, BYTE, DOUBLE, FLOAT, INT, REST, UUID, WireType
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
