"""Read back the gzipped NBT files an Adapter writes: just enough for tests to look inside.

`mscts.adapters.nbt` only writes. This reads the same tags into plain Python values: a
Compound becomes a dict, a List a list, an IntArray a tuple, and each number its value
(a Byte, Int or Long an int; a Float or Double a float).
"""

import gzip
import struct
from dataclasses import dataclass, field

_NUMBERS = {1: ">b", 2: ">h", 3: ">i", 4: ">q", 5: ">f", 6: ">d"}
_STRING, _LIST, _COMPOUND, _INT_ARRAY = 8, 9, 10, 11

type Value = int | float | str | list[Value] | tuple[int, ...] | dict[str, Value]
"""A tag read back as a plain Python value."""


@dataclass
class _Reader:
    data: bytes
    at: int = field(default=0)

    def take(self, count: int) -> bytes:
        chunk = self.data[self.at : self.at + count]
        self.at += count
        return chunk

    def unpack(self, fmt: str) -> int | float:
        value = struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]
        if not isinstance(value, int | float):
            msg = f"expected a number, got {value!r}"
            raise TypeError(msg)
        return value

    def count(self, fmt: str) -> int:
        value = self.unpack(fmt)
        if not isinstance(value, int):
            msg = f"expected an integer, got {value!r}"
            raise TypeError(msg)
        return value

    def string(self) -> str:
        length = self.count(">H")
        return self.take(length).decode("utf-8")

    def payload(self, tag: int) -> Value:
        if tag in _NUMBERS:
            return self.unpack(_NUMBERS[tag])
        if tag == _STRING:
            return self.string()
        if tag == _LIST:
            inner = self.take(1)[0]
            return [self.payload(inner) for _ in range(self.count(">i"))]
        if tag == _INT_ARRAY:
            return tuple(self.count(">i") for _ in range(self.count(">i")))
        if tag == _COMPOUND:
            return self.compound()
        msg = f"tag {tag} is not one an Adapter writes"
        raise ValueError(msg)

    def compound(self) -> dict[str, Value]:
        out: dict[str, Value] = {}
        while (tag := self.take(1)[0]) != 0:
            name = self.string()
            out[name] = self.payload(tag)
        return out


def read_gzipped(data: bytes) -> dict[str, Value]:
    """The root compound of a gzipped NBT file."""
    reader = _Reader(gzip.decompress(data))
    tag = reader.take(1)[0]
    if tag != _COMPOUND:
        msg = f"the root tag is {tag}, not a compound"
        raise ValueError(msg)
    reader.string()  # the root's name, empty in a world save
    return reader.compound()
