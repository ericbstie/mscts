"""The Reference's flat world (`level_chunk_with_light`), pinned against the decoder.

The decoder itself (position and sections, single valued and indirect palettes) lives in
`scripts/research/chunkformat.py`, loaded here by path: both a plain research script and
these pins reuse the very same code, and tests need no reachable `scripts` package for it.
"""

import importlib.util
import types
from pathlib import Path

from mscts.codec.packets import Direction, Packet, State
from mscts.transcript import Transcript

_CHUNKFORMAT = Path(__file__).resolve().parents[2] / "scripts" / "research" / "chunkformat.py"


def _load_chunkformat() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("research_chunkformat", _CHUNKFORMAT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_chunkformat = _load_chunkformat()
Chunk = _chunkformat.Chunk
Section = _chunkformat.Section
decode_chunk = _chunkformat.decode_chunk
SECTION_ENTRIES = _chunkformat.SECTION_ENTRIES
BIOME_ENTRIES = _chunkformat.BIOME_ENTRIES
LAYER = _chunkformat.LAYER
OVERWORLD_SECTIONS = _chunkformat.OVERWORLD_SECTIONS

# What the Reference sends for the default ServerSpec's flat world (docs/research/
# 2026-09-26-pumpkin.md, "A native world save"; pinned by
# tests/reference/test_flat_world_reference.py).
FLAT_BOTTOM_LAYERS = (88, 10, 10, 9)  # block state ids of y = -64 .. -61: then air (0)
FLAT_BIOME = 41  # every biome cell: the plains, by the registry order the join sent
FLAT_SPAWN_Y = -60.0  # standing on the top layer


def unlike_the_reference_flat_world(chunk: "_chunkformat.Chunk") -> list[str]:
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
