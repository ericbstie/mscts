"""Helpers for pinning a wire type's exact bytes."""

from mscts.codec.schema import WireType
from mscts.codec.wire import Reader, Writer


def written[T](wire_type: WireType[T], value: object) -> bytes:
    """The bytes `wire_type` writes for `value`."""
    writer = Writer()
    wire_type.write(writer, value)
    return writer.to_bytes()


def read_all[T](wire_type: WireType[T], data: bytes) -> T:
    """The value `wire_type` reads from `data`, which it must consume entirely."""
    reader = Reader(data)
    value = wire_type.read(reader)
    reader.expect_end()
    return value
