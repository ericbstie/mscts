"""Hermetic tests for scripts/research/chunkformat.py: a chunk's sections, through the codec."""

import importlib.util
import types
from pathlib import Path

import pytest
from support.chunks import (
    indirect_container,
    level_chunk_payload,
    packed_longs,
    section_bytes,
    single_valued,
)

from mscts.codec.wire import WireError

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research" / "chunkformat.py"


@pytest.fixture
def chunkformat() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("chunkformat", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_decode_chunk_reads_the_position_and_single_valued_palettes(
    chunkformat: types.ModuleType,
) -> None:
    section = section_bytes(single_valued(5), single_valued(41), block_count=16)
    payload = level_chunk_payload(3, -2, [section])

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
    section = section_bytes(
        indirect_container(state_values, state_palette, bits=1, width=4),
        indirect_container(biome_values, biome_palette, bits=1, width=1),
    )
    payload = level_chunk_payload(0, 0, [section])

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
    direct_states = bytes([9]) + packed_longs(values, 16)
    payload = level_chunk_payload(0, 0, [section_bytes(direct_states, single_valued(41))])

    chunk = chunkformat.decode_chunk(payload, section_count=1)

    assert chunk.sections[0].states == tuple(values)
    assert chunk.sections[0].layer(0) == frozenset({35_722})


def test_decode_chunk_reads_several_sections_in_order(chunkformat: types.ModuleType) -> None:
    bottom = section_bytes(single_valued(1), single_valued(41), block_count=256)
    top = section_bytes(single_valued(0), single_valued(41))
    payload = level_chunk_payload(0, 0, [bottom, top])

    chunk = chunkformat.decode_chunk(payload, section_count=2)

    assert [section.block_count for section in chunk.sections] == [256, 0]
    assert chunk.sections[0].states == (1,) * chunkformat.SECTION_ENTRIES
    assert chunk.sections[1].states == (0,) * chunkformat.SECTION_ENTRIES


def test_decode_chunk_keeps_only_the_sections_asked_for(chunkformat: types.ModuleType) -> None:
    payload = level_chunk_payload(
        0,
        0,
        [
            section_bytes(single_valued(1), single_valued(41)),
            section_bytes(single_valued(2), single_valued(41)),
        ],
    )
    (only,) = chunkformat.decode_chunk(payload, section_count=1).sections
    assert only.states == (1,) * chunkformat.SECTION_ENTRIES


def test_decode_chunk_refuses_fewer_sections_than_asked_for(chunkformat: types.ModuleType) -> None:
    payload = level_chunk_payload(0, 0, [section_bytes(single_valued(1), single_valued(41))])
    with pytest.raises(ValueError, match="1 section"):
        chunkformat.decode_chunk(payload, section_count=2)


def test_decode_chunk_refuses_a_payload_that_is_not_a_whole_chunk(
    chunkformat: types.ModuleType,
) -> None:
    payload = level_chunk_payload(0, 0, [section_bytes(single_valued(1), single_valued(41))])
    with pytest.raises(WireError):
        chunkformat.decode_chunk(payload[:-1], section_count=1)  # the light cut short
