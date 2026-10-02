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

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from mscts.codec.wire import Reader, WireError, Writer

_STRING_MAX_LENGTH = 32767


class SchemaError(ValueError):
    """A schema declaration that can never be valid, raised when it is defined."""


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
class _VarLong:
    def read(self, reader: Reader) -> int:
        return reader.var_long()

    def write(self, writer: Writer, value: object) -> None:
        writer.var_long(_integer(value))


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


@dataclass(frozen=True, slots=True)
class _Bool:
    def read(self, reader: Reader) -> bool:
        return reader.bool_()

    def write(self, writer: Writer, value: object) -> None:
        if not isinstance(value, bool):
            msg = f"expected a bool, got {type(value).__name__}"
            raise WireError(msg)
        writer.bool_(value=value)


@dataclass(frozen=True, slots=True)
class _Uuid:
    def read(self, reader: Reader) -> uuid.UUID:
        return reader.uuid()

    def write(self, writer: Writer, value: object) -> None:
        if not isinstance(value, uuid.UUID):
            msg = f"expected a UUID, got {type(value).__name__}"
            raise WireError(msg)
        writer.uuid(value)


@dataclass(frozen=True, slots=True)
class _Byte:
    def read(self, reader: Reader) -> int:
        return reader.byte()

    def write(self, writer: Writer, value: object) -> None:
        writer.byte(_integer(value))


_UBYTE_MAX = 0xFF


@dataclass(frozen=True, slots=True)
class _UByte:
    def read(self, reader: Reader) -> int:
        return reader.raw(1)[0]

    def write(self, writer: Writer, value: object) -> None:
        number = _integer(value)
        if not 0 <= number <= _UBYTE_MAX:
            msg = f"{number} out of range for an Unsigned Byte"
            raise WireError(msg)
        writer.raw(bytes([number]))


@dataclass(frozen=True, slots=True)
class _Short:
    def read(self, reader: Reader) -> int:
        return reader.short()

    def write(self, writer: Writer, value: object) -> None:
        writer.short(_integer(value))


@dataclass(frozen=True, slots=True)
class _Int:
    def read(self, reader: Reader) -> int:
        return reader.int_()

    def write(self, writer: Writer, value: object) -> None:
        writer.int_(_integer(value))


def _real(value: object) -> float:
    if not isinstance(value, float):
        msg = f"expected a float, got {type(value).__name__}"
        raise WireError(msg)
    return value


@dataclass(frozen=True, slots=True)
class _Float:
    def read(self, reader: Reader) -> float:
        return reader.float_()

    def write(self, writer: Writer, value: object) -> None:
        writer.float_(_real(value))


@dataclass(frozen=True, slots=True)
class _Double:
    def read(self, reader: Reader) -> float:
        return reader.double()

    def write(self, writer: Writer, value: object) -> None:
        writer.double(_real(value))


@dataclass(frozen=True, slots=True)
class _Rest:
    def read(self, reader: Reader) -> bytes:
        return reader.rest()

    def write(self, writer: Writer, value: object) -> None:
        if not isinstance(value, bytes):
            msg = f"expected bytes, got {type(value).__name__}"
            raise WireError(msg)
        writer.raw(value)


BYTE: WireType[int] = _Byte()
"""Byte: a signed 8-bit integer."""

UBYTE: WireType[int] = _UByte()
"""Unsigned Byte: 0 to 255 (`FriendlyByteBuf.readUnsignedByte`)."""

SHORT: WireType[int] = _Short()
"""Short: a signed 16-bit integer, big-endian."""

INT: WireType[int] = _Int()
"""Int: a signed 32-bit integer, big-endian."""

FLOAT: WireType[float] = _Float()
"""Float: IEEE 754 binary32. Writes only a float that binary32 holds exactly."""

DOUBLE: WireType[float] = _Double()
"""Double: IEEE 754 binary64. Writes only a float."""

REST: WireType[bytes] = _Rest()
"""Byte Array running to the end of the packet (e.g. a plugin message's data); last field only."""

BOOL: WireType[bool] = _Bool()
"""Boolean: 0x00 or 0x01 (anything else is invalid; docs/PLAN.md, stricter than the client)."""

UUID: WireType[uuid.UUID] = _Uuid()
"""UUID: 128 bits, big-endian."""

VAR_INT: WireType[int] = _VarInt()
"""VarInt: a signed 32-bit integer, 1 to 5 bytes."""

VAR_LONG: WireType[int] = _VarLong()
"""VarLong: a signed 64-bit integer, 1 to 10 bytes."""

USHORT: WireType[int] = _UShort()
"""Unsigned Short: 0 to 65535, big-endian."""

LONG: WireType[int] = _Long()
"""Long: a signed 64-bit integer, big-endian."""


@dataclass(frozen=True, slots=True)
class EntityId:
    """An entity id, carried as a VarInt or an Int: a type of its own so a field can be found.

    A Comparison recognises every field that holds an entity id by `isinstance(type,
    EntityId)`, whatever the packet (the renumbering needs no list of packets). Use the
    constants `ENTITY_ID` (VarInt), `ENTITY_ID_INT` and `ENTITY_ID_OPTIONAL`.

    Attributes:
        wire: How the id is carried: `VAR_INT` or `INT`.
        optional: The value is the id plus one on the wire, 0 meaning no entity, as vanilla
            writes a damage event's source ids; it reads as the id, or None for none.
        zero_is_none: The value is the id itself, but 0 means no entity, as vanilla writes a
            lead's holder; it reads as the id, or None for none.
    """

    wire: WireType[int]
    optional: bool = False
    zero_is_none: bool = False

    def __post_init__(self) -> None:
        """Reject an id that is both kinds of optional.

        Raises:
            SchemaError: `optional` and `zero_is_none` are both true.
        """
        if self.optional and self.zero_is_none:
            msg = "an entity id is optional or zero_is_none, not both"
            raise SchemaError(msg)

    def read(self, reader: Reader) -> int | None:
        """Consume the id, or None if the wire value is 0 and 0 means no entity."""
        value = self.wire.read(reader)
        if not (self.optional or self.zero_is_none):
            return value
        return None if value == 0 else value - self._shift

    def write(self, writer: Writer, value: object) -> None:
        """Append `value`, an int, or None for no entity if the id may be none."""
        if not (self.optional or self.zero_is_none):
            self.wire.write(writer, value)
            return
        if value is None:
            self.wire.write(writer, 0)
            return
        entity_id = _integer(value)
        if entity_id + self._shift == 0:
            msg = f"{entity_id} is not an entity id (it would read back as no entity)"
            raise WireError(msg)
        self.wire.write(writer, entity_id + self._shift)

    @property
    def _shift(self) -> int:
        """What is added to the id on the wire: 1 if `optional`, else 0."""
        return 1 if self.optional else 0


ENTITY_ID = EntityId(VAR_INT)
"""An entity id as a VarInt (spawn, movement, metadata, …)."""

ENTITY_ID_INT = EntityId(INT)
"""An entity id as an Int (`login`, `entity_event`, `set_entity_link`)."""

ENTITY_ID_INT_OR_NONE = EntityId(INT, zero_is_none=True)
"""An entity id as an Int, or None as 0 (`set_entity_link`'s holder: 0 detaches the lead)."""

ENTITY_ID_OPTIONAL = EntityId(VAR_INT, optional=True)
"""An entity id or None, as a VarInt holding the id plus one (0 is none)."""


@dataclass(frozen=True, slots=True)
class String:
    """String (n): UTF-8 behind a VarInt byte-length prefix.

    Attributes:
        max_length: The protocol's `n`, in UTF-16 code units, from 1 to 32767.
    """

    max_length: int

    def __post_init__(self) -> None:
        """Reject a `max_length` the protocol does not allow.

        Raises:
            SchemaError: `max_length` is not an int in 1..32767.
        """
        if isinstance(self.max_length, bool) or not isinstance(self.max_length, int):
            msg = f"String max_length must be an int, got {type(self.max_length).__name__}"
            raise SchemaError(msg)
        if not 1 <= self.max_length <= _STRING_MAX_LENGTH:
            msg = f"String max_length {self.max_length} is not in 1..{_STRING_MAX_LENGTH}"
            raise SchemaError(msg)

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

    @property
    def fields(self) -> dict[str, WireType[object]]:
        """The declared fields by name, in wire order (a copy: changing it changes nothing)."""
        return dict(self._fields)

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


IDENTIFIER: WireType[str] = String(_STRING_MAX_LENGTH)
"""Identifier (`minecraft:thing`): on the wire, a String (32767)."""


@dataclass(frozen=True, slots=True)
class PrefixedArray[T]:
    """Prefixed Array of X: a VarInt length, then that many elements.

    Its value is a list. Errors are prefixed with the element's index, so a nested
    failure reads `entries: 3: name: ...`. A length greater than the bytes left is
    refused before reading any element: no element type takes less than a byte.

    Attributes:
        element: Each element's wire type.
        max_length: The most elements allowed, or None for no bound beyond the above.
    """

    element: WireType[T]
    max_length: int | None = None

    def __post_init__(self) -> None:
        """Reject a `max_length` that is not a non-negative int.

        Raises:
            SchemaError: `max_length` is negative, or not an int.
        """
        if self.max_length is None:
            return
        if isinstance(self.max_length, bool) or not isinstance(self.max_length, int):
            msg = f"PrefixedArray max_length must be an int, got {type(self.max_length).__name__}"
            raise SchemaError(msg)
        if self.max_length < 0:
            msg = f"PrefixedArray max_length {self.max_length} is negative"
            raise SchemaError(msg)

    def read(self, reader: Reader) -> list[T]:
        """Consume the length, then each element."""
        length = reader.var_int()
        if length < 0:
            msg = f"array length {length} is negative"
            raise WireError(msg)
        self._check_length(length)
        if length > reader.remaining:
            msg = f"array length {length} exceeds the {reader.remaining} byte(s) left"
            raise WireError(msg)
        values = []
        for index in range(length):
            try:
                values.append(self.element.read(reader))
            except WireError as exc:
                msg = f"{index}: {exc}"
                raise WireError(msg) from exc
        return values

    def write(self, writer: Writer, value: object) -> None:
        """Append `value`, a list or tuple of elements, behind its length."""
        if not isinstance(value, list | tuple):
            msg = f"expected a list or tuple, got {type(value).__name__}"
            raise WireError(msg)
        self._check_length(len(value))
        writer.var_int(len(value))
        for index, item in enumerate(value):
            try:
                self.element.write(writer, item)
            except WireError as exc:
                msg = f"{index}: {exc}"
                raise WireError(msg) from exc

    def _check_length(self, length: int) -> None:
        if self.max_length is not None and length > self.max_length:
            msg = f"array length {length} exceeds max {self.max_length}"
            raise WireError(msg)


@dataclass(frozen=True, slots=True)
class PrefixedOptional[T]:
    """Prefixed Optional X: a Boolean, then X if it is true. Its value is X's, or None.

    Attributes:
        element: The wire type of the value when present.
    """

    element: WireType[T]

    def read(self, reader: Reader) -> T | None:
        """Consume the presence flag (strictly 0x00 or 0x01), then the value if present."""
        return self.element.read(reader) if reader.bool_() else None

    def write(self, writer: Writer, value: object) -> None:
        """Append `value`: None as absent, anything else as present."""
        writer.bool_(value=value is not None)
        if value is not None:
            self.element.write(writer, value)


class Tagged:
    """A VarInt that picks one of several named variants, each with its own payload or none.

    Its value is a dict of exactly two keys: `tag_key` holds the variant's name and
    `value_key` its payload (None for a variant with no wire type). A variant's id is its
    position in `variants`. An id no variant has is a `WireError`, as is a name no variant
    has when writing. Errors inside a payload are prefixed with the variant's name.
    """

    __slots__ = ("_ids", "_tag_key", "_value_key", "_variants")

    def __init__(
        self,
        tag_key: str,
        value_key: str,
        variants: Sequence[tuple[str, WireType[object] | None]],
    ) -> None:
        """Declare the variants, in id order.

        Raises:
            SchemaError: The keys are equal, there is no variant, or two variants share a name.
        """
        if tag_key == value_key:
            msg = f"Tagged tag_key and value_key are both {tag_key!r}"
            raise SchemaError(msg)
        if not variants:
            msg = "Tagged needs at least one variant"
            raise SchemaError(msg)
        ids = {name: number for number, (name, _) in enumerate(variants)}
        if len(ids) != len(variants):
            msg = "Tagged has a variant name twice"
            raise SchemaError(msg)
        self._tag_key = tag_key
        self._value_key = value_key
        self._variants = tuple(variants)
        self._ids = ids

    @property
    def tag_key(self) -> str:
        """The key of the value that holds the variant's name."""
        return self._tag_key

    @property
    def value_key(self) -> str:
        """The key of the value that holds the variant's payload."""
        return self._value_key

    @property
    def names(self) -> tuple[str, ...]:
        """The variant names, in id order."""
        return tuple(name for name, _ in self._variants)

    @property
    def variants(self) -> tuple[tuple[str, WireType[object] | None], ...]:
        """Each variant's name and wire type (None: no payload), in id order."""
        return self._variants

    def read(self, reader: Reader) -> dict[str, object]:
        """Consume the id, then the payload of the variant it names."""
        tag = reader.var_int()
        if not 0 <= tag < len(self._variants):
            msg = f"unknown {self._tag_key} id {tag}"
            raise WireError(msg)
        name, wire_type = self._variants[tag]
        payload = None
        if wire_type is not None:
            try:
                payload = wire_type.read(reader)
            except WireError as exc:
                msg = f"{name}: {exc}"
                raise WireError(msg) from exc
        return {self._tag_key: name, self._value_key: payload}

    def write(self, writer: Writer, value: object) -> None:
        """Append `value`, a dict of the tag key and the value key, as the id then the payload."""
        keys = (self._tag_key, self._value_key)
        if not isinstance(value, Mapping):
            msg = f"expected a mapping of {keys[0]} and {keys[1]}, got {type(value).__name__}"
            raise WireError(msg)
        given = {str(key): item for key, item in value.items()}
        problems = [f"missing key {key}" for key in keys if key not in given]
        problems += [f"unexpected key {key}" for key in sorted(given) if key not in keys]
        if problems:
            raise WireError("; ".join(problems))
        name = given[self._tag_key]
        if not isinstance(name, str) or name not in self._ids:
            msg = f"unknown {self._tag_key} {name!r}"
            raise WireError(msg)
        wire_type = self._variants[self._ids[name]][1]
        payload = given[self._value_key]
        if wire_type is None and payload is not None:
            msg = f"{name}: takes no {self._value_key}"
            raise WireError(msg)
        writer.var_int(self._ids[name])
        if wire_type is not None:
            try:
                wire_type.write(writer, payload)
            except WireError as exc:
                msg = f"{name}: {exc}"
                raise WireError(msg) from exc


_NBT_END, _NBT_BYTE_ARRAY, _NBT_STRING, _NBT_LIST, _NBT_COMPOUND = 0, 7, 8, 9, 10
_NBT_INT_ARRAY, _NBT_LONG_ARRAY = 11, 12
_NBT_FIXED_SIZES = {1: 1, 2: 2, 3: 4, 4: 8, 5: 4, 6: 8}
"""Payload sizes of Byte, Short, Int, Long, Float and Double tags."""
_NBT_ARRAY_ELEMENT_SIZES = {_NBT_BYTE_ARRAY: 1, _NBT_INT_ARRAY: 4, _NBT_LONG_ARRAY: 8}
_NBT_MAX_DEPTH = 512
"""How deep lists and compounds may nest: vanilla's `NbtAccounter` MAX_STACK_DEPTH."""


def _skip_nbt_tag(reader: Reader) -> None:
    """Consume one network NBT tag (a type byte, then its unnamed payload), checking it.

    Iterative, with an explicit stack, so a deeply nested tag cannot exhaust Python's.
    """
    pending: int | None = reader.raw(1)[0]
    stack: list[list[int]] = []  # [tag type, list element type, list elements left]
    while True:
        if pending is not None:
            _skip_nbt_payload(reader, pending, stack)
            pending = None
        if not stack:
            return
        frame = stack[-1]
        if frame[0] == _NBT_LIST:
            if frame[2] == 0:
                stack.pop()
            else:
                frame[2] -= 1
                pending = frame[1]
        else:  # a compound: named entries until TAG_End
            entry_type = reader.raw(1)[0]
            if entry_type == _NBT_END:
                stack.pop()
            else:
                reader.raw(reader.ushort())  # the entry's name (modified UTF-8, unchecked)
                pending = entry_type


def _skip_nbt_payload(reader: Reader, tag_type: int, stack: list[list[int]]) -> None:
    """Consume the payload of a `tag_type` tag, pushing a list or compound onto `stack`."""
    if tag_type == _NBT_END:
        return
    if tag_type in _NBT_FIXED_SIZES:
        reader.raw(_NBT_FIXED_SIZES[tag_type])
    elif tag_type in _NBT_ARRAY_ELEMENT_SIZES:
        reader.raw(_nbt_length(reader) * _NBT_ARRAY_ELEMENT_SIZES[tag_type])
    elif tag_type == _NBT_STRING:
        reader.raw(reader.ushort())  # modified UTF-8, kept as bytes, unchecked
    elif tag_type in {_NBT_LIST, _NBT_COMPOUND}:
        if len(stack) >= _NBT_MAX_DEPTH:
            msg = f"nested deeper than {_NBT_MAX_DEPTH}"
            raise WireError(msg)
        if tag_type == _NBT_COMPOUND:
            stack.append([_NBT_COMPOUND, 0, 0])
            return
        element_type = reader.raw(1)[0]
        length = _nbt_length(reader)
        if element_type == _NBT_END and length > 0:
            msg = f"a list of {length} element(s) has no element type"
            raise WireError(msg)
        stack.append([_NBT_LIST, element_type, length])
    else:
        msg = f"invalid tag type {tag_type}"
        raise WireError(msg)


def _nbt_length(reader: Reader) -> int:
    length = reader.int_()
    if length < 0:
        msg = f"negative length {length}"
        raise WireError(msg)
    return length


@dataclass(frozen=True, slots=True)
class _Nbt:
    def read(self, reader: Reader) -> bytes:
        start = reader.remaining
        view = Reader(reader.peek_rest())
        try:
            _skip_nbt_tag(view)
        except WireError as exc:
            msg = f"NBT: {exc}"
            raise WireError(msg) from exc
        return reader.raw(start - view.remaining)

    def write(self, writer: Writer, value: object) -> None:
        if not isinstance(value, bytes):
            msg = f"expected bytes, got {type(value).__name__}"
            raise WireError(msg)
        reader = Reader(value)
        try:
            _skip_nbt_tag(reader)
            reader.expect_end()
        except WireError as exc:
            msg = f"NBT: {exc}"
            raise WireError(msg) from exc
        writer.raw(value)


NBT: WireType[bytes] = _Nbt()
"""NBT in network form (an unnamed root tag), kept as its exact bytes.

Checked structurally as vanilla's `NbtIo` reads it: known tag types, non-negative lengths,
no untyped non-empty list, at most 512 levels of lists and compounds. String contents
(modified UTF-8) are not decoded; being bytes, they are still compared exactly. Unlike
vanilla, no byte quota is enforced beyond the frame's own limits.
"""

_POSITION_FIELDS = (("x", 26, 38), ("z", 26, 12), ("y", 12, 0))
"""Each coordinate's name, width in bits, and shift within the Long."""


@dataclass(frozen=True, slots=True)
class _Position:
    def read(self, reader: Reader) -> dict[str, int]:
        packed = reader.long() & 0xFFFF_FFFF_FFFF_FFFF
        position = {}
        for name, width, shift in _POSITION_FIELDS:
            value = (packed >> shift) & ((1 << width) - 1)
            position[name] = value - (1 << width) if value >> (width - 1) else value
        return {name: position[name] for name in ("x", "y", "z")}

    def write(self, writer: Writer, value: object) -> None:
        # Exactly the names x, y and z, each an int: the Schema says what is wrong if not.
        Schema(x=_Int(), y=_Int(), z=_Int()).write(Writer(), value)
        given = (
            {str(key): item for key, item in value.items()} if isinstance(value, Mapping) else {}
        )
        packed = 0
        for name, width, shift in _POSITION_FIELDS:
            coordinate = _integer(given.get(name))
            if not -(1 << (width - 1)) <= coordinate < 1 << (width - 1):
                msg = f"{name}: {coordinate} out of range for {width} signed bits"
                raise WireError(msg)
            packed |= (coordinate & ((1 << width) - 1)) << shift
        writer.long(packed - (1 << 64) if packed >> 63 else packed)


POSITION: WireType[dict[str, int]] = _Position()
"""Position: x, z (26 bits each) and y (12 bits), signed, packed into a Long: {x, y, z}."""

_LP_VEC3_QUANTUM_BITS = 15
_LP_VEC3_SCALE_MAX = (1 << 34) - 1
"""The largest scale: the VarInt extension is an unsigned 32-bit value, shifted left by two."""
_LP_VEC3_CONTINUATION = 4
_LP_VEC3_LOW_SCALE_MAX = 3
"""The two low bits of the first byte hold a scale of 0 to 3; a larger one needs the extension."""


@dataclass(frozen=True, slots=True)
class _LpVec3:
    """A vector in net.minecraft.network.LpVec3's form: a scale and three 15-bit quanta."""

    def read(self, reader: Reader) -> dict[str, int]:
        lowest = reader.raw(1)[0]
        if lowest == 0:
            return {"scale": 0, "x": 0, "y": 0, "z": 0}
        middle = reader.raw(1)[0]
        high = int.from_bytes(reader.raw(4), "big")
        packed = high << 16 | middle << 8 | lowest
        scale = lowest & _LP_VEC3_LOW_SCALE_MAX
        if lowest & _LP_VEC3_CONTINUATION:
            extension = reader.var_int() & 0xFFFF_FFFF
            if extension == 0:
                msg = "LpVec3: continuation flag with no scale extension"
                raise WireError(msg)
            scale |= extension << 2
        mask = (1 << _LP_VEC3_QUANTUM_BITS) - 1
        return {
            "scale": scale,
            "x": (packed >> 3) & mask,
            "y": (packed >> 18) & mask,
            "z": (packed >> 33) & mask,
        }

    def write(self, writer: Writer, value: object) -> None:
        # Exactly the names scale, x, y and z, each an int: the Schema says what is wrong if not.
        Schema(scale=_Long(), x=_Long(), y=_Long(), z=_Long()).write(Writer(), value)
        given = (
            {str(key): item for key, item in value.items()} if isinstance(value, Mapping) else {}
        )
        scale = _integer(given.get("scale"))
        if not 0 <= scale <= _LP_VEC3_SCALE_MAX:
            msg = f"scale: {scale} out of range for 0..{_LP_VEC3_SCALE_MAX}"
            raise WireError(msg)
        quanta = {name: _integer(given.get(name)) for name in ("x", "y", "z")}
        for name, quantum in quanta.items():
            if not 0 <= quantum < 1 << _LP_VEC3_QUANTUM_BITS:
                msg = f"{name}: {quantum} out of range for {_LP_VEC3_QUANTUM_BITS} bits"
                raise WireError(msg)
        continuation = scale > _LP_VEC3_LOW_SCALE_MAX
        packed = (
            quanta["z"] << 33
            | quanta["y"] << 18
            | quanta["x"] << 3
            | (_LP_VEC3_CONTINUATION if continuation else 0)
            | scale & _LP_VEC3_LOW_SCALE_MAX
        )
        if packed & 0xFF == 0:
            if scale == 0 and not any(quanta.values()):
                writer.raw(b"\x00")
                return
            msg = "LpVec3: a lowest byte of 0 would read back as the zero vector"
            raise WireError(msg)
        writer.raw(bytes([packed & 0xFF, packed >> 8 & 0xFF]))
        writer.raw((packed >> 16).to_bytes(4, "big"))
        if continuation:
            extension = scale >> 2
            writer.var_int(extension - (1 << 32) if extension >> 31 else extension)


LP_VEC3: WireType[dict[str, int]] = _LpVec3()
"""LpVec3 (velocity): {scale, x, y, z}, the scale and three 15-bit quanta exactly as on the wire.

A quantum q stands for `(q * 2 / 32766 - 1) * scale` (32767 counts as 32766). The integers are
kept, not that float, because two different encodings can give the same float (vanilla rounds
the scale up and the quanta to nearest), and a Comparison must see a difference in bytes.
A continuation flag with no scale extension is refused: it would read as a flagless scale.
"""
