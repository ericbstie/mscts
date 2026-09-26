"""Hermetic tests for scripts/research/chunkformat.py: single-valued and indirect palettes."""

import importlib.util
import struct
import types
from pathlib import Path

import pytest

from mscts.codec.wire import Writer

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research" / "chunkformat.py"


@pytest.fixture
def chunkformat() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("chunkformat", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _single(value: int) -> bytes:
    """A "single valued" Paletted Container: bits 0, then the one VarInt id."""
    return Writer().raw(bytes([0])).var_int(value).to_bytes()


def _indirect(values: list[int], palette: list[int], bits: int) -> bytes:
    """An indirect Paletted Container: bits, the palette, then the packed Data Array."""
    per_long = 64 // bits
    writer = Writer().raw(bytes([bits])).var_int(len(palette))
    for entry in palette:
        writer.var_int(entry)
    indices = [palette.index(value) for value in values]
    for start in range(0, len(indices), per_long):
        word = 0
        for offset, index in enumerate(indices[start : start + per_long]):
            word |= index << (offset * bits)
        writer.raw(struct.pack(">Q", word))
    return writer.to_bytes()


def _section(states: bytes, biomes: bytes, *, block_count: int = 0) -> bytes:
    return struct.pack(">hh", block_count, 0) + states + biomes


def _payload(x: int, z: int, sections: list[bytes]) -> bytes:
    data = b"".join(sections)
    return Writer().int_(x).int_(z).var_int(0).var_int(len(data)).raw(data).to_bytes()


def test_decode_chunk_reads_the_position_and_single_valued_palettes(
    chunkformat: types.ModuleType,
) -> None:
    section = _section(_single(5), _single(41), block_count=16)
    payload = _payload(3, -2, [section])

    chunk = chunkformat.decode_chunk(payload, section_count=1)

    assert (chunk.x, chunk.z) == (3, -2)
    (only,) = chunk.sections
    assert only.block_count == 16
    assert only.states == (5,) * chunkformat.SECTION_ENTRIES
    assert only.biomes == (41,) * chunkformat.BIOME_ENTRIES
    assert only.layer(0) == frozenset({5})


def test_decode_chunk_reads_indirect_palettes(chunkformat: types.ModuleType) -> None:
    state_palette = [0, 7]
    state_values = [state_palette[0]] * 2048 + [state_palette[1]] * (
        chunkformat.SECTION_ENTRIES - 2048
    )
    biome_palette = [10, 20]
    biome_values = [biome_palette[0]] * 32 + [biome_palette[1]] * (chunkformat.BIOME_ENTRIES - 32)
    section = _section(
        _indirect(state_values, state_palette, bits=1),
        _indirect(biome_values, biome_palette, bits=1),
    )
    payload = _payload(0, 0, [section])

    chunk = chunkformat.decode_chunk(payload, section_count=1)

    (only,) = chunk.sections
    assert only.states == tuple(state_values)
    assert only.biomes == tuple(biome_values)
    assert only.layer(7) == frozenset({0})
    assert only.layer(8) == frozenset({7})


def test_decode_chunk_reads_several_sections_in_order(chunkformat: types.ModuleType) -> None:
    bottom = _section(_single(1), _single(41), block_count=256)
    top = _section(_single(0), _single(41))
    payload = _payload(0, 0, [bottom, top])

    chunk = chunkformat.decode_chunk(payload, section_count=2)

    assert [section.block_count for section in chunk.sections] == [256, 0]
    assert chunk.sections[0].states == (1,) * chunkformat.SECTION_ENTRIES
    assert chunk.sections[1].states == (0,) * chunkformat.SECTION_ENTRIES


def test_decode_chunk_rejects_a_direct_palette(chunkformat: types.ModuleType) -> None:
    direct_states = Writer().raw(bytes([9])).to_bytes()  # above max_indirect (8) for states
    section = _section(direct_states, _single(41))
    payload = _payload(0, 0, [section])

    with pytest.raises(ValueError, match="direct palette"):
        chunkformat.decode_chunk(payload, section_count=1)
