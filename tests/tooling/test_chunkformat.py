"""Hermetic tests for scripts/research/chunkformat.py: a chunk's sections, through the codec."""

import importlib.util
import struct
import types
from pathlib import Path

import pytest

from mscts.codec.wire import WireError, Writer

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


def _packed(indices: list[int], width: int) -> bytes:
    """Entries of `width` bits in big-endian Longs, lowest bits first, none split across two."""
    per_long = 64 // width
    data = b""
    for start in range(0, len(indices), per_long):
        word = 0
        for offset, index in enumerate(indices[start : start + per_long]):
            word |= index << (offset * width)
        data += struct.pack(">Q", word)
    return data


def _indirect(values: list[int], palette: list[int], bits: int, width: int) -> bytes:
    """A list or hash palette container: `bits` sent, the palette, entries at `width` bits.

    The client reads block states sent with 1 to 4 bits at 4 bits per entry, biomes at the
    bits sent (`Strategy.getConfigurationForBitCount`).
    """
    writer = Writer().raw(bytes([bits])).var_int(len(palette))
    for entry in palette:
        writer.var_int(entry)
    return writer.raw(_packed([palette.index(value) for value in values], width)).to_bytes()


def _section(states: bytes, biomes: bytes, *, block_count: int = 0) -> bytes:
    return struct.pack(">hh", block_count, 0) + states + biomes


def _payload(x: int, z: int, sections: list[bytes]) -> bytes:
    """A whole `level_chunk_with_light` of `sections`: no heightmaps, block entities or light."""
    data = b"".join(sections)
    writer = Writer().int_(x).int_(z).var_int(0).var_int(len(data)).raw(data).var_int(0)
    for _ in range(6):  # four empty light masks, no sky arrays, no block arrays
        writer.var_int(0)
    return writer.to_bytes()


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


def test_decode_chunk_reads_one_bit_block_states_at_four_bits_an_entry(
    chunkformat: types.ModuleType,
) -> None:
    # The decoder this module had before the codec read them at 1 bit, and got them wrong.
    state_palette = [0, 7]
    state_values = [state_palette[0]] * 2048 + [state_palette[1]] * (
        chunkformat.SECTION_ENTRIES - 2048
    )
    biome_palette = [10, 20]
    biome_values = [biome_palette[0]] * 32 + [biome_palette[1]] * (chunkformat.BIOME_ENTRIES - 32)
    section = _section(
        _indirect(state_values, state_palette, bits=1, width=4),
        _indirect(biome_values, biome_palette, bits=1, width=1),
    )
    payload = _payload(0, 0, [section])

    chunk = chunkformat.decode_chunk(payload, section_count=1)

    (only,) = chunk.sections
    assert only.states == tuple(state_values)
    assert only.biomes == tuple(biome_values)
    assert only.layer(7) == frozenset({0})
    assert only.layer(8) == frozenset({7})


def test_decode_chunk_reads_a_direct_palette_at_16_bits_an_entry(
    chunkformat: types.ModuleType,
) -> None:
    # 26.3 has 35,723 block states: the client's global palette takes 16 bits, whatever is sent.
    values = [35_722] * 256 + [1] * (chunkformat.SECTION_ENTRIES - 256)
    direct_states = bytes([9]) + _packed(values, 16)
    payload = _payload(0, 0, [_section(direct_states, _single(41))])

    chunk = chunkformat.decode_chunk(payload, section_count=1)

    assert chunk.sections[0].states == tuple(values)
    assert chunk.sections[0].layer(0) == frozenset({35_722})


def test_decode_chunk_reads_several_sections_in_order(chunkformat: types.ModuleType) -> None:
    bottom = _section(_single(1), _single(41), block_count=256)
    top = _section(_single(0), _single(41))
    payload = _payload(0, 0, [bottom, top])

    chunk = chunkformat.decode_chunk(payload, section_count=2)

    assert [section.block_count for section in chunk.sections] == [256, 0]
    assert chunk.sections[0].states == (1,) * chunkformat.SECTION_ENTRIES
    assert chunk.sections[1].states == (0,) * chunkformat.SECTION_ENTRIES


def test_decode_chunk_keeps_only_the_sections_asked_for(chunkformat: types.ModuleType) -> None:
    payload = _payload(0, 0, [_section(_single(1), _single(41)), _section(_single(2), _single(41))])
    (only,) = chunkformat.decode_chunk(payload, section_count=1).sections
    assert only.states == (1,) * chunkformat.SECTION_ENTRIES


def test_decode_chunk_refuses_fewer_sections_than_asked_for(chunkformat: types.ModuleType) -> None:
    payload = _payload(0, 0, [_section(_single(1), _single(41))])
    with pytest.raises(ValueError, match="1 section"):
        chunkformat.decode_chunk(payload, section_count=2)


def test_decode_chunk_refuses_a_payload_that_is_not_a_whole_chunk(
    chunkformat: types.ModuleType,
) -> None:
    payload = _payload(0, 0, [_section(_single(1), _single(41))])
    with pytest.raises(WireError):
        chunkformat.decode_chunk(payload[:-1], section_count=1)  # the light cut short
