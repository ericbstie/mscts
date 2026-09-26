"""Just enough of `level_chunk_with_light` to see which blocks a chunk's layers hold.

Layout: minecraft.wiki `Java_Edition_protocol/Chunk_format`, revision 3661930 (packet
structure, Chunk Section and Paletted Container structures, Data Array format). Only the
chunk's position and its sections are read; the block entities and light that follow
the sections are not.
"""

import struct
from dataclasses import dataclass

from mscts.codec.packets import Direction, Packet, State
from mscts.codec.wire import Reader
from mscts.transcript import Transcript

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
    x: int
    z: int
    sections: tuple[Section, ...]  # bottom to top


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


# What the Reference sends for the default ServerSpec's flat world (docs/research/
# 2026-09-26-pumpkin.md, "A native world save"; pinned by
# tests/reference/test_flat_world_reference.py). The overworld is 24 sections high.
OVERWORLD_SECTIONS = 24
FLAT_BOTTOM_LAYERS = (88, 10, 10, 9)  # block state ids of y = -64 .. -61: then air (0)
FLAT_BIOME = 41  # every biome cell: the plains, by the registry order the join sent
FLAT_SPAWN_Y = -60.0  # standing on the top layer


def unlike_the_reference_flat_world(chunk: Chunk) -> list[str]:
    """How `chunk` differs from the Reference's flat world (empty: not at all)."""
    differences = []
    bottom = chunk.sections[0]
    expected = (*FLAT_BOTTOM_LAYERS, *(0,) * (16 - len(FLAT_BOTTOM_LAYERS)))
    for y, state in enumerate(expected):
        if bottom.layer(y) != {state}:
            differences.append(f"y={y - 64}: {sorted(bottom.layer(y))}, not [{state}]")
    if bottom.block_count != LAYER * len(FLAT_BOTTOM_LAYERS):
        differences.append(f"bottom section block count {bottom.block_count}")
    for index, section in enumerate(chunk.sections[1:], start=1):
        if section.block_count != 0 or set(section.states) != {0}:
            differences.append(f"section {index} is not all air")
    biomes = {biome for section in chunk.sections for biome in section.biomes}
    if biomes != {FLAT_BIOME}:
        differences.append(f"biomes {sorted(biomes)}")
    return [f"chunk ({chunk.x}, {chunk.z}) {difference}" for difference in differences]


def play_packets(transcript: Transcript, name: str) -> list[Packet]:
    """The clientbound play packets called `name` that `transcript` recorded, in order."""
    return [
        event.packet
        for event in transcript.events
        if (event.packet.state, event.packet.direction, event.packet.name)
        == (State.PLAY, Direction.CLIENTBOUND, name)
    ]
