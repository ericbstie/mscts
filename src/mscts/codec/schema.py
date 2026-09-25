"""The schema mechanism: how a packet's named fields map to wire types.

A wire type reads one value from a `Reader` and writes one to a `Writer`.
A `Schema` is an ordered set of named fields, each with a wire type, and is
itself a wire type, so it nests as a compound value. Composite types to come
(Prefixed Optional X, Prefixed Array of X, …) wrap any wire type, a Schema
included.

Wire types are context-free: a field never reads its siblings. When a
field's presence, length or shape depends on another field, a single
composite wire type owns both the field it depends on and the dependent part.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from mscts.codec.wire import Reader, WireError, Writer


class WireType[T](Protocol):
    """How one field's value is read from and written to the wire."""

    def read(self, reader: Reader) -> T:
        """Consume one value from `reader`.

        Raises:
            WireError: The bytes are not a valid value of this type.
        """

    def write(self, writer: Writer, value: object) -> None:
        """Append `value` to `writer`.

        Raises:
            WireError: `value` is not a value this type can encode.
        """


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"expected an int, got {type(value).__name__}"
        raise WireError(msg)
    return value


@dataclass(frozen=True, slots=True)
class _VarInt:
    def read(self, reader: Reader) -> int:
        return reader.var_int()

    def write(self, writer: Writer, value: object) -> None:
        writer.var_int(_integer(value))


@dataclass(frozen=True, slots=True)
class _UShort:
    def read(self, reader: Reader) -> int:
        return reader.ushort()

    def write(self, writer: Writer, value: object) -> None:
        writer.ushort(_integer(value))


@dataclass(frozen=True, slots=True)
class _Long:
    def read(self, reader: Reader) -> int:
        return reader.long()

    def write(self, writer: Writer, value: object) -> None:
        writer.long(_integer(value))


VAR_INT: WireType[int] = _VarInt()
"""VarInt: a signed 32-bit integer, 1 to 5 bytes."""

USHORT: WireType[int] = _UShort()
"""Unsigned Short: 0 to 65535, big-endian."""

LONG: WireType[int] = _Long()
"""Long: a signed 64-bit integer, big-endian."""


@dataclass(frozen=True, slots=True)
class String:
    """String (n): UTF-8 behind a VarInt byte-length prefix.

    Attributes:
        max_length: The protocol's `n`, in UTF-16 code units.
    """

    max_length: int

    def read(self, reader: Reader) -> str:
        """Consume a String of at most `max_length` UTF-16 code units."""
        return reader.string(max_length=self.max_length)

    def write(self, writer: Writer, value: object) -> None:
        """Append `value`, a str of at most `max_length` UTF-16 code units."""
        if not isinstance(value, str):
            msg = f"expected a str, got {type(value).__name__}"
            raise WireError(msg)
        writer.string(value, max_length=self.max_length)


class Schema:
    """The ordered, named fields of a packet, or of a compound value inside one.

    `Schema(protocol_version=VAR_INT, server_address=String(255))` reads and
    writes its fields in declaration order. Its value is a `dict` keyed by
    field name. Field names are the snake_case of the wiki's field names.
    """

    __slots__ = ("_fields",)

    def __init__(self, **fields: WireType[object]) -> None:
        """Declare the fields, in wire order."""
        self._fields = tuple(fields.items())

    def read(self, reader: Reader) -> dict[str, object]:
        """Consume every field, in order.

        Raises:
            WireError: A field's bytes are invalid; the message names the field.
        """
        values: dict[str, object] = {}
        for name, wire_type in self._fields:
            try:
                values[name] = wire_type.read(reader)
            except WireError as exc:
                msg = f"{name}: {exc}"
                raise WireError(msg) from exc
        return values

    def write(self, writer: Writer, value: object) -> None:
        """Append every field of `value`, a mapping of field name to value, in order.

        Raises:
            WireError: `value` does not have exactly the declared field names, or a
                field's value cannot be encoded; the message names the fields.
        """
        if not isinstance(value, Mapping):
            msg = f"expected a mapping of field names to values, got {type(value).__name__}"
            raise WireError(msg)
        given = dict(value.items())
        declared = {name for name, _ in self._fields}
        missing = [name for name, _ in self._fields if name not in given]
        unexpected = sorted(str(name) for name in given if name not in declared)
        problems = []
        if missing:
            problems.append(f"missing field(s) {', '.join(missing)}")
        if unexpected:
            problems.append(f"unexpected field(s) {', '.join(unexpected)}")
        if problems:
            msg = "; ".join(problems)
            raise WireError(msg)
        for name, wire_type in self._fields:
            try:
                wire_type.write(writer, given[name])
            except WireError as exc:
                msg = f"{name}: {exc}"
                raise WireError(msg) from exc
