"""The schema's field types: each reads what it writes, and refuses what it cannot encode."""

import uuid

import pytest

from mscts.codec.schema import BOOL, UUID, WireType
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


def test_uuid_round_trips() -> None:
    assert written(UUID, SAMPLE_UUID) == SAMPLE_UUID.bytes
    assert read_all(UUID, SAMPLE_UUID.bytes) == SAMPLE_UUID


@pytest.mark.parametrize("value", [str(SAMPLE_UUID), SAMPLE_UUID.bytes, SAMPLE_UUID.int])
def test_uuid_refuses_a_value_that_is_not_a_uuid(value: object) -> None:
    with pytest.raises(WireError, match="expected a UUID"):
        written(UUID, value)
