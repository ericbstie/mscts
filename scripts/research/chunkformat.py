"""A chunk's position and sections, spelled out block by block, from a `level_chunk_with_light`.

The codec decodes the payload (`mscts/codec/schemas/play/chunks.py`): all of it and strictly,
every palette a server may send, the global one too (docs/research/2026-10-02-chunks-light.md).
This module only spells each section's block states and biomes out, entry by entry, so a pin
can ask which blocks a layer holds.

`tests/support/chunks.py` loads this module by path (so it stays reusable from a plain
script, and tests need no reachable `scripts` package) and builds its Reference-specific
pins (the flat world's expected layers) on top of it; `scripts/research/join.py` does the
same for `--chunks N`.
"""

from dataclasses import dataclass
from typing import cast

from mscts.codec.schemas.play.chunks import BIOMES, BLOCK_STATES, CLIENTBOUND
from mscts.codec.wire import Reader

SECTION_ENTRIES = 4096  # 16 x 16 x 16 block states, y slowest, then z, then x
BIOME_ENTRIES = 64  # 4 x 4 x 4 biome cells
LAYER = 256  # one y level of a section

# The overworld dimension type's height (-64..320, the vanilla dimension registry, not any
# Adapter's own choice) is 384 blocks, i.e. 24 sections: how many an overworld
# `level_chunk_with_light` has (docs/research/2026-09-26-pumpkin.md).
OVERWORLD_SECTIONS = 24

_CHUNK = CLIENTBOUND["minecraft:level_chunk_with_light"]


@dataclass(frozen=True, slots=True)
class Section:
    """One 16-block-high chunk section."""

    block_count: int  # its non-air blocks, as the server counted them
    states: tuple[int | None, ...]  # global block state ids; None past the palette
    biomes: tuple[int | None, ...]  # biome registry ids; None past the palette

    def layer(self, y: int) -> frozenset[int | None]:
        """The block states at section-relative height `y` (0..15)."""
        return frozenset(self.states[y * LAYER : (y + 1) * LAYER])


@dataclass(frozen=True, slots=True)
class Chunk:
    """A chunk's position and its decoded sections, bottom to top."""

    x: int
    z: int
    sections: tuple[Section, ...]


def decode_chunk(payload: bytes, section_count: int) -> Chunk:
    """The position and first `section_count` sections of a `level_chunk_with_light` payload.

    Raises WireError (a ValueError) if the codec refuses the payload, and ValueError if it
    has fewer than `section_count` sections.
    """
    reader = Reader(payload)
    fields = _CHUNK.read(reader)
    reader.expect_end()
    sections = cast("list[dict[str, object]]", fields["sections"])
    if len(sections) < section_count:
        msg = f"the chunk has {len(sections)} section(s), fewer than {section_count}"
        raise ValueError(msg)
    return Chunk(
        x=cast("int", fields["chunk_x"]),
        z=cast("int", fields["chunk_z"]),
        sections=tuple(
            Section(
                block_count=cast("int", section["block_count"]),
                states=BLOCK_STATES.values(cast("dict[str, object]", section["block_states"])),
                biomes=BIOMES.values(cast("dict[str, object]", section["biomes"])),
            )
            for section in sections[:section_count]
        ),
    )
