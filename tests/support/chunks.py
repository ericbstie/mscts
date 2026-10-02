"""The Reference's flat world, its chunks and where a join puts the player, pinned.

The codec decodes a chunk; `scripts/research/chunkformat.py`, loaded here by path, spells its
sections out block by block: both a plain research script and these pins reuse the very same
code, and tests need no reachable `scripts` package for it.
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


def unlike_a_flat_join(positions: list[Packet]) -> list[str]:
    """How the `player_position`s of a join differ from the Reference's (empty: not at all).

    The first is teleport id 1 at the spawn. Any more are the server putting the player back
    where it is, the first one's pose with the next ids: how many come is a race against the
    server's first tick, so it is not a difference (docs/research/2026-09-26-join.md, "More
    than one `player_position` at join").
    """
    if not positions:
        return ["no player_position"]
    first = positions[0].fields or {}
    differences = []
    if first.get("teleport_id") != 1:
        differences.append(
            f"the first player_position has teleport id {first.get('teleport_id')}, not 1"
        )
    if first.get("y") != FLAT_SPAWN_Y:
        differences.append(
            f"the first player_position is at y={first.get('y')}, not {FLAT_SPAWN_Y}"
        )
    for number, later in enumerate(positions[1:], start=2):
        if (later.fields or {}) != {**first, "teleport_id": number}:
            differences.append(
                f"player_position {number} is not the first one's pose with teleport id {number}"
            )
    return differences


def play_packets(transcript: Transcript, name: str) -> list[Packet]:
    """The clientbound play packets called `name` that `transcript` recorded, in order."""
    return [
        event.packet
        for event in transcript.events
        if (event.packet.state, event.packet.direction, event.packet.name)
        == (State.PLAY, Direction.CLIENTBOUND, name)
    ]
