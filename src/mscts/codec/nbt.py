"""Network NBT decoded into values, as the vanilla client reads it (#335).

`schema.NBT` keeps a tag as its exact bytes, so a packet's fields compare byte for byte. A
Comparison that needs what the client reads from a tag (a text component, `compare.py`)
decodes those bytes here. The rules are vanilla 26.3's `NbtIo` (javap on the client):

- a root is a type byte, then that type's payload, with no name (network NBT);
- a String is modified UTF-8, as `DataInput.readUTF` reads it (`_modified_utf8`);
- a compound keeps the last value of a repeated name (`CompoundTag$1.loadCompound`:
  `HashMap.put`);
- lists and compounds nest at most 512 deep (`NbtAccounter`'s `MAX_STACK_DEPTH`), as
  `schema.NBT`'s walker checks.

A list of compounds is decoded as sent: the client's unwrapping of `{"": value}` elements
(`ListTag.addAndUnwrap`) is left to whoever reads the value. No byte quota is enforced.
"""

import struct
from collections.abc import Callable
from dataclasses import dataclass

from mscts.codec.wire import Reader, WireError


@dataclass(frozen=True, slots=True)
class Numeric:
    """A numeric tag: `kind` is its type (`byte`, `short`, `int`, `long`, `float`, `double`).

    Two tags of different types are different values, as they are different `Tag`s to the
    client, even when their numbers are equal.
    """

    kind: str
    value: int | float


@dataclass(frozen=True, slots=True)
class Array:
    """An array tag: `kind` is its type (`byte_array`, `int_array`, `long_array`)."""

    kind: str
    values: tuple[int, ...]


type Value = Numeric | Array | str | list[Value] | dict[str, Value] | None
"""A decoded tag: None for TAG_End (a root with no tag), a str for a String, a list for a
List, a dict for a Compound."""

_END, _STRING, _LIST, _COMPOUND = 0, 8, 9, 10

_NUMBERS: dict[int, tuple[str, Callable[[Reader], int | float]]] = {
    1: ("byte", Reader.byte),
    2: ("short", Reader.short),
    3: ("int", Reader.int_),
    4: ("long", Reader.long),
    5: ("float", Reader.float_),
    6: ("double", Reader.double),
}
"""Each numeric tag type: its kind and how its payload is read."""

_ARRAYS: dict[int, tuple[str, Callable[[Reader], int]]] = {
    7: ("byte_array", Reader.byte),
    11: ("int_array", Reader.int_),
    12: ("long_array", Reader.long),
}
"""Each array tag type: its kind and how one element is read."""

_MAX_DEPTH = 512
"""How deep lists and compounds may nest: vanilla's `NbtAccounter` MAX_STACK_DEPTH."""


def decode(data: bytes) -> Value:
    """Decode `data`, exactly one network NBT tag, into its value.

    Raises:
        WireError: `data` is not one tag `schema.NBT` would read whole, or a String in it is
            not modified UTF-8 that `DataInput.readUTF` reads.
    """
    reader = Reader(data)
    try:
        value = _tag(reader, reader.raw(1)[0])
        reader.expect_end()
    except WireError as exc:
        msg = f"NBT: {exc}"
        raise WireError(msg) from exc
    return value


class _List:
    """A List being read: its elements so far, their type, and how many are left."""

    def __init__(self, element_type: int, left: int) -> None:
        self.value: list[Value] = []
        self.element_type = element_type
        self.left = left

    def add(self, item: Value) -> None:
        self.value.append(item)

    def next_type(self, reader: Reader) -> int | None:
        """The type of the next element, or None when every element is read."""
        del reader
        if not self.left:
            return None
        self.left -= 1
        return self.element_type


class _Compound:
    """A Compound being read: its entries so far, and the name of the entry being read."""

    def __init__(self) -> None:
        self.value: dict[str, Value] = {}
        self.name = ""

    def add(self, item: Value) -> None:
        self.value[self.name] = item

    def next_type(self, reader: Reader) -> int | None:
        """Read the next entry's type and name; None at the compound's TAG_End."""
        entry_type = reader.raw(1)[0]
        if entry_type == _END:
            return None
        self.name = _modified_utf8(reader.raw(reader.ushort()))
        return entry_type


type _Open = _List | _Compound


def _tag(reader: Reader, tag_type: int) -> Value:
    """Read the payload of a `tag_type` tag, and every tag in it.

    Iterative, with an explicit stack of open lists and compounds, so a tag 512 deep does not
    exhaust Python's.
    """
    stack: list[_Open] = []
    pending: int | None = tag_type
    while True:
        if pending is not None:
            item = _payload(reader, pending, stack)
            if not isinstance(item, _List | _Compound):
                if not stack:
                    return item
                stack[-1].add(item)
        pending = stack[-1].next_type(reader)
        if pending is None:
            done = stack.pop()
            if not stack:
                return done.value
            stack[-1].add(done.value)


def _payload(reader: Reader, tag_type: int, stack: list[_Open]) -> Value | _Open:
    """Read a `tag_type` payload; a List or Compound is opened on `stack` and returned open."""
    if tag_type == _END:
        return None
    if tag_type in _NUMBERS:
        kind, read = _NUMBERS[tag_type]
        return Numeric(kind, read(reader))
    if tag_type in _ARRAYS:
        kind, read_element = _ARRAYS[tag_type]
        return Array(kind, tuple(read_element(reader) for _ in range(_length(reader))))
    if tag_type == _STRING:
        return _modified_utf8(reader.raw(reader.ushort()))
    if tag_type in {_LIST, _COMPOUND}:
        return _opened(reader, tag_type, stack)
    msg = f"invalid tag type {tag_type}"
    raise WireError(msg)


def _opened(reader: Reader, tag_type: int, stack: list[_Open]) -> _Open:
    """Open a List or Compound on `stack`, reading a List's element type and length."""
    if len(stack) >= _MAX_DEPTH:
        msg = f"nested deeper than {_MAX_DEPTH}"
        raise WireError(msg)
    opened: _Open
    if tag_type == _COMPOUND:
        opened = _Compound()
    else:
        element_type = reader.raw(1)[0]
        length = _length(reader)
        if element_type == _END and length > 0:
            msg = f"a list of {length} element(s) has no element type"
            raise WireError(msg)
        opened = _List(element_type, length)
    stack.append(opened)
    return opened


def _length(reader: Reader) -> int:
    length = reader.int_()
    if length < 0:
        msg = f"negative length {length}"
        raise WireError(msg)
    return length


_ONE_BYTE_TOP = 0x80
_CONTINUATION_MASK, _CONTINUATION = 0xC0, 0x80
_TWO_BYTE_MASK, _TWO_BYTE = 0xE0, 0xC0
_THREE_BYTE_MASK, _THREE_BYTE = 0xF0, 0xE0


def _modified_utf8(data: bytes) -> str:
    """`data` as `DataInputStream.readUTF` reads it: Java's modified UTF-8.

    Each character is one byte below 0x80, or a two- or three-byte form whose further bytes
    are `10xxxxxx`; an overlong form is taken, a four-byte form refused. Each character is a
    UTF-16 code unit, so a surrogate pair becomes one code point, and a lone surrogate stays.

    Raises:
        WireError: readUTF would throw `UTFDataFormatException`.
    """
    units: list[int] = []
    position = 0
    while position < len(data):
        first = data[position]
        if first < _ONE_BYTE_TOP:
            units.append(first)
            position += 1
            continue
        size, mask = _form(first)
        rest = data[position + 1 : position + size]
        if len(rest) < size - 1 or any(b & _CONTINUATION_MASK != _CONTINUATION for b in rest):
            msg = f"malformed modified UTF-8 at byte {position}"
            raise WireError(msg)
        unit = first & mask
        for byte in rest:
            unit = unit << 6 | byte & 0x3F
        units.append(unit)
        position += size
    return struct.pack(f">{len(units)}H", *units).decode("utf-16-be", "surrogatepass")


def _form(first: int) -> tuple[int, int]:
    """The size of the form `first` starts, and the mask of its own bits.

    Raises:
        WireError: `first` starts no form readUTF takes (a continuation or four-byte lead).
    """
    if first & _TWO_BYTE_MASK == _TWO_BYTE:
        return 2, 0x1F
    if first & _THREE_BYTE_MASK == _THREE_BYTE:
        return 3, 0x0F
    msg = f"malformed modified UTF-8: byte {first:#04x}"
    raise WireError(msg)
