"""A minimal, strict NBT writer: just enough for the world saves an Adapter writes.

Java Edition's binary NBT (minecraft.wiki `NBT_format`, revision 3725656): big-endian,
a named root compound, strings as a u16 byte length and modified UTF-8. Only the tags a
world save needs exist here. Every value is checked against its tag's range, so nothing
is silently wrapped or truncated. Nothing reads NBT back: the codec keeps network NBT as
checked bytes (codec/schema.py).

A value is typed by its Python type: `str` is a String, a `Mapping[str, Tag]` a Compound
(in its own key order), and the numbers, lists and arrays are the wrappers below.
"""

import gzip
import math
import struct
from collections.abc import Mapping
from dataclasses import dataclass

type Tag = Byte | Int | Long | Float | Double | str | List | IntArray | Compound
type Compound = Mapping[str, Tag]

_END, _BYTE, _INT, _LONG, _FLOAT, _DOUBLE = 0, 1, 3, 4, 5, 6
_STRING, _LIST, _COMPOUND, _INT_ARRAY = 8, 9, 10, 11
_MAX_STRING_BYTES = 0xFFFF  # a u16 length
_MAX_LENGTH = 2**31 - 1  # an Int length (lists, arrays)


class NbtError(ValueError):
    """A value no NBT tag can hold as given."""


def _integer(value: object, bits: int) -> int:
    if type(value) is not int:  # bool is an int, but no NBT tag
        msg = f"{value!r} is not an int"
        raise NbtError(msg)
    if not -(2 ** (bits - 1)) <= value < 2 ** (bits - 1):
        msg = f"{value} does not fit a signed {bits}-bit integer"
        raise NbtError(msg)
    return value


@dataclass(frozen=True, slots=True)
class Byte:
    """TAG_Byte: -128..127. A boolean is a Byte 0 or 1."""

    value: int


@dataclass(frozen=True, slots=True)
class Int:
    """TAG_Int: a signed 32-bit integer."""

    value: int


@dataclass(frozen=True, slots=True)
class Long:
    """TAG_Long: a signed 64-bit integer."""

    value: int


@dataclass(frozen=True, slots=True)
class Float:
    """TAG_Float: a binary32 (the value must be exactly one)."""

    value: float


@dataclass(frozen=True, slots=True)
class Double:
    """TAG_Double: a binary64."""

    value: float


@dataclass(frozen=True, slots=True)
class List:
    """TAG_List: tags of one type. An empty list has element type TAG_End, as vanilla's."""

    items: tuple[Tag, ...]


@dataclass(frozen=True, slots=True)
class IntArray:
    """TAG_Int_Array: signed 32-bit integers."""

    values: tuple[int, ...]


def _type_id(tag: Tag) -> int:  # noqa: PLR0911 (one return per tag type)
    match tag:
        case Byte():
            return _BYTE
        case Int():
            return _INT
        case Long():
            return _LONG
        case Float():
            return _FLOAT
        case Double():
            return _DOUBLE
        case str():
            return _STRING
        case List():
            return _LIST
        case IntArray():
            return _INT_ARRAY
        case Mapping():
            return _COMPOUND
    msg = f"{tag!r} is no NBT tag"
    raise NbtError(msg)


def _string(text: object) -> bytes:
    """`text` as NBT writes a string: a u16 byte length, then modified UTF-8.

    Modified UTF-8 equals UTF-8 except for U+0000 and characters outside the BMP, which
    are refused rather than encoded (no world save needs them).
    """
    if not isinstance(text, str):
        msg = f"{text!r} is not a string"
        raise NbtError(msg)
    if any(char == "\0" or ord(char) > 0xFFFF for char in text):  # noqa: PLR2004 (the BMP)
        msg = f"{text!r} holds U+0000 or a character outside the BMP"
        raise NbtError(msg)
    try:
        encoded = text.encode()
    except UnicodeEncodeError as error:  # a lone surrogate
        msg = f"{text!r} is not valid Unicode: {error}"
        raise NbtError(msg) from error
    if len(encoded) > _MAX_STRING_BYTES:
        msg = f"a string of {len(encoded)} bytes is longer than {_MAX_STRING_BYTES}"
        raise NbtError(msg)
    return struct.pack(">H", len(encoded)) + encoded


def _length(count: int) -> bytes:
    if count > _MAX_LENGTH:
        msg = f"{count} items are more than an Int length can count"
        raise NbtError(msg)
    return struct.pack(">i", count)


def _float(value: object) -> float:
    if type(value) is not float:
        msg = f"{value!r} is not a float"
        raise NbtError(msg)
    return value


def _binary32(value: object) -> bytes:
    single = _float(value)
    try:
        packed = struct.pack(">f", single)
    except OverflowError as error:
        msg = f"{single!r} is too large for a binary32"
        raise NbtError(msg) from error
    if math.isfinite(single) and struct.unpack(">f", packed)[0] != single:
        msg = f"{single!r} is not exactly a binary32"
        raise NbtError(msg)
    return packed


_INTEGERS: Mapping[type, tuple[str, int]] = {Byte: (">b", 8), Int: (">i", 32), Long: (">q", 64)}


def _payload(tag: Tag) -> bytes:  # noqa: PLR0911 (one return per tag type)
    match tag:
        case Byte() | Int() | Long():
            layout, bits = _INTEGERS[type(tag)]
            return struct.pack(layout, _integer(tag.value, bits))
        case Float(value):
            return _binary32(value)
        case Double(value):
            return struct.pack(">d", _float(value))
        case str():
            return _string(tag)
        case List(items):
            return _list(items)
        case IntArray(values):
            return _length(len(values)) + b"".join(
                struct.pack(">i", _integer(value, 32)) for value in values
            )
        case Mapping():
            return _compound(tag)
    msg = f"{tag!r} is no NBT tag"
    raise NbtError(msg)


def _list(items: tuple[Tag, ...]) -> bytes:
    types = {_type_id(item) for item in items}
    if len(types) > 1:
        msg = f"a list holds tags of one type, not of types {sorted(types)}"
        raise NbtError(msg)
    element = types.pop() if types else _END
    return bytes([element]) + _length(len(items)) + b"".join(_payload(item) for item in items)


def _compound(compound: Compound) -> bytes:
    named = [
        bytes([_type_id(tag)]) + _string(name) + _payload(tag) for name, tag in compound.items()
    ]
    return b"".join(named) + bytes([_END])


def encode(root: Compound) -> bytes:
    """`root` as an NBT file's uncompressed bytes: a Compound named "" (as vanilla's)."""
    return bytes([_COMPOUND]) + _string("") + _compound(root)


def gzipped(root: Compound) -> bytes:
    """`root` as a gzipped NBT file (level.dat, data/*.dat), the same bytes on every call.

    One gzip member with a zero modification time, so the file depends on `root` alone.
    """
    return gzip.compress(encode(root), mtime=0)
