"""Just enough of `level_chunk_with_light` to see which blocks a chunk's layers hold.

Layout: minecraft.wiki `Java_Edition_protocol/Chunk_format`, revision 3661930 (packet
structure, Chunk Section and Paletted Container structures, Data Array format). Only the
chunk's position and its sections are read; the block entities and light that follow
the sections are not.

`tests/support/chunks.py` loads this module by path (so it stays reusable from a plain
script, and tests need no reachable `scripts` package) and builds its Reference-specific
pins (the flat world's expected layers) on top of it; `scripts/research/join.py` does the
same for `--chunks N`.
"""

import struct
from dataclasses import dataclass

from mscts.codec.wire import Reader

SECTION_ENTRIES = 4096  # 16 x 16 x 16 block states, y slowest, then z, then x
BIOME_ENTRIES = 64  # 4 x 4 x 4 biome cells
LAYER = 256  # one y level of a section


@dataclass(frozen=True, slots=True)
class Section:
    """One 16-block-high chunk section."""

    block_count: int  # its non-air blocks, as the server counted them
    states: tuple[int, ...]  # global block state ids
    biomes: tuple[int, ...]  # biome registry ids

    def layer(self, y: int) -> frozenset[int]:
        """The block states at section-relative height `y` (0..15)."""
        return frozenset(self.states[y * LAYER : (y + 1) * LAYER])


@dataclass(frozen=True, slots=True)
class Chunk:
    """A chunk's position and its decoded sections, bottom to top."""

    x: int
    z: int
    sections: tuple[Section, ...]


def _paletted(reader: Reader, entries: int, max_indirect: int) -> tuple[int, ...]:
    bits = reader.raw(1)[0]
    if bits > max_indirect:
        msg = f"a direct palette ({bits} bits per entry) is not decoded here"
        raise ValueError(msg)
    if bits == 0:  # single valued: the palette is one id, and there is no data array
        return (reader.var_int(),) * entries
    palette = [reader.var_int() for _ in range(reader.var_int())]
    per_long = 64 // bits
    values: list[int] = []
    for _ in range(-(-entries // per_long)):  # the array's length is not sent (1.21.5+)
        (word,) = struct.unpack(">Q", reader.raw(8))
        values.extend((word >> (index * bits)) & ((1 << bits) - 1) for index in range(per_long))
    return tuple(palette[value] for value in values[:entries])


def decode_chunk(payload: bytes, section_count: int) -> Chunk:
    """The position and first `section_count` sections of a `level_chunk_with_light` payload.

    Handles the single valued and indirect palettes only: a direct (global) one raises
    ValueError. A payload too short for this layout raises the Reader's error.
    """
    reader = Reader(payload)
    x, z = reader.int_(), reader.int_()
    for _ in range(reader.var_int()):  # heightmaps: a type, then a prefixed array of Long
        reader.var_int()
        reader.raw(8 * reader.var_int())
    data = Reader(reader.raw(reader.var_int()))
    sections = []
    for _ in range(section_count):
        block_count = struct.unpack(">h", data.raw(2))[0]
        data.raw(2)  # fluid count
        states = _paletted(data, SECTION_ENTRIES, max_indirect=8)
        biomes = _paletted(data, BIOME_ENTRIES, max_indirect=3)
        sections.append(Section(block_count, states, biomes))
    return Chunk(x, z, tuple(sections))
