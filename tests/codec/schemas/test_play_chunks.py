"""The chunk and light packets of Target 26.3: each decodes into fields and re-encodes exactly.

Layouts come from the 26.3 client jar (`javap` on each packet's `STREAM_CODEC` and on
`PalettedContainer`, docs/research/2026-10-02-chunks-light.md). The first chunks are recorded from
vanilla 26.3 and Pumpkin (the 2026-09-30 joins, docs/research/2026-09-30-gameplay-survey.md); the
other payloads are built by hand from the layout, as a join sends none of them.
"""

from pathlib import Path
from typing import cast

import pytest
from support.play import CLIENTBOUND, CODEC, decode_error, encode_error, round_trip

from mscts.codec.packets import State
from mscts.codec.schemas.play.chunks import BIOMES, BLOCK_STATES, PalettedContainer
from mscts.codec.wire import Reader, WireError, Writer

CHUNK = "minecraft:level_chunk_with_light"
LIGHT_UPDATE = "minecraft:light_update"
FORGET = "minecraft:forget_level_chunk"
CENTER = "minecraft:set_chunk_cache_center"
RADIUS = "minecraft:set_chunk_cache_radius"
CHUNKS_BIOMES = "minecraft:chunks_biomes"

FULL_LIGHT = "8010" + "ff" * 2048
"""A light array: its length (2048, a VarInt), then 4096 light levels of 15, two to a byte."""


# The small packets: a chunk position, the loading area's centre and radius.


def test_the_centre_of_the_loading_area_is_a_chunk_x_and_z() -> None:
    round_trip(CENTER, {"chunk_x": 0, "chunk_z": 0}, "0000")  # recorded at join, both servers
    round_trip(CENTER, {"chunk_x": -1, "chunk_z": 2}, "ffffffff0f02")


def test_the_radius_of_the_loading_area_is_a_view_distance() -> None:
    round_trip(RADIUS, {"view_distance": 10}, "0a")


def test_a_chunk_to_forget_is_one_long_with_z_in_its_high_half() -> None:
    round_trip(FORGET, {"chunk_z": 2, "chunk_x": -1}, "00000002ffffffff")


# Light: four bit sets (a length, then the bytes of `BitSet.toByteArray`, lowest bit first), then
# the sky arrays and the block arrays.

LIGHT = {
    "sky_light_mask": b"\x02",  # light section 1
    "block_light_mask": b"",
    "empty_sky_light_mask": b"\x01",  # light section 0
    "empty_block_light_mask": b"",
    "sky_light_arrays": [b"\xff" * 2048],
    "block_light_arrays": [],
}
LIGHT_HEX = "0102" + "00" + "0101" + "00" + "01" + FULL_LIGHT + "00"


def test_a_light_update_is_a_chunk_position_and_its_light() -> None:
    round_trip(
        LIGHT_UPDATE, {"chunk_x": 3, "chunk_z": -2, "data": LIGHT}, "03feffffff0f" + LIGHT_HEX
    )


def test_a_light_mask_keeps_the_zero_bytes_after_its_last_bit() -> None:
    # The client reads them (`BitSet.valueOf`) and ignores them; vanilla never writes them.
    light = {**LIGHT, "sky_light_mask": b"\x02\x00"}
    round_trip(
        LIGHT_UPDATE, {"chunk_x": 0, "chunk_z": 0, "data": light}, "0000" + "020200" + LIGHT_HEX[4:]
    )


def test_a_light_array_of_up_to_2048_bytes_is_read() -> None:
    # `byteArray(2048)` reads any length up to 2048; the client fails later on one that is not
    # 2048 bytes, and only if the mask uses it.
    light = {**LIGHT, "sky_light_arrays": [b"\x0f\x0f"]}
    hex_light = "0102000101000102" + "0f0f" + "00"
    round_trip(LIGHT_UPDATE, {"chunk_x": 0, "chunk_z": 0, "data": light}, "0000" + hex_light)


def test_a_light_array_longer_than_2048_bytes_is_refused() -> None:
    error = decode_error(LIGHT_UPDATE, "0000" + "0102000101000181" + "10" + "00" * 2049 + "00")
    assert "sky_light_arrays: 0" in error
    assert "2049" in error


def test_a_light_array_too_long_to_write_is_refused() -> None:
    light = {**LIGHT, "sky_light_arrays": [bytes(2049)]}
    assert "2049" in encode_error(LIGHT_UPDATE, {"chunk_x": 0, "chunk_z": 0, "data": light})


# The first chunk each server sent at join (chunk 0 0 of the flat world): heightmaps, 24 sections,
# no block entities, then light. Both servers encode the sections the same; their light differs.

DATA = Path(__file__).parent / "data"
AIR = {"bits": 0, "palette": 0, "data": b""}
PLAINS = {"bits": 0, "palette": 41, "data": b""}
"""Every biome cell of the flat world: the plains, the 41st entry of the biome registry sent."""
RECORDED = {
    # file, then the sky mask, the empty sky mask and the empty block mask
    "vanilla 26.3": ("vanilla-26.3-first-chunk.bin", b"\x06", b"\x01", b"\x07"),
    "Pumpkin b8382a8a": (
        "pumpkin-26.3-first-chunk.bin",
        b"\xfe\xff\xff\x01",  # light sections 1 to 24
        b"\x01\x00\x00\x02",  # 0 and 25
        b"\xff\xff\xff\x03",  # 0 to 25
    ),
}


@pytest.mark.parametrize(
    ("file", "sky", "empty_sky", "empty_block"), RECORDED.values(), ids=RECORDED.keys()
)
def test_a_recorded_first_chunk_decodes_and_encodes_byte_for_byte(
    file: str, sky: bytes, empty_sky: bytes, empty_block: bytes
) -> None:
    data = bytes([CODEC.packet_id(State.PLAY, CLIENTBOUND, CHUNK)]) + (DATA / file).read_bytes()

    packet = CODEC.decode(State.PLAY, CLIENTBOUND, data)

    fields = cast("dict[str, object]", packet.fields)
    assert (fields["chunk_x"], fields["chunk_z"]) == (0, 0)
    heightmaps = cast("list[dict[str, object]]", fields["heightmaps"])
    # WORLD_SURFACE, MOTION_BLOCKING and MOTION_BLOCKING_NO_LEAVES, 9 bits for each of 256 columns
    assert [(entry["type"], len(cast("list[int]", entry["data"]))) for entry in heightmaps] == [
        (1, 37),
        (4, 37),
        (5, 37),
    ]
    sections = cast("list[dict[str, object]]", fields["sections"])
    assert len(sections) == 24
    bottom = sections[0]
    assert (bottom["block_count"], bottom["fluid_count"]) == (1024, 0)
    states = cast("dict[str, object]", bottom["block_states"])
    assert (states["bits"], states["palette"]) == (4, [88, 10, 9, 0])
    assert all(section["biomes"] == PLAINS for section in sections)
    assert all(section["block_states"] == AIR for section in sections[1:])
    assert fields["block_entities"] == []
    light = cast("dict[str, object]", fields["light"])
    masks = ("sky_light_mask", "block_light_mask", "empty_sky_light_mask", "empty_block_light_mask")
    assert [light[mask] for mask in masks] == [sky, b"", empty_sky, empty_block]
    sky_arrays = cast("list[bytes]", light["sky_light_arrays"])
    assert len(sky_arrays) == int.from_bytes(sky, "little").bit_count()  # one for each bit
    assert {len(array) for array in sky_arrays} == {2048}
    assert light["block_light_arrays"] == []
    assert CODEC.encode(State.PLAY, CLIENTBOUND, CHUNK, fields) == data


def test_the_recorded_bottom_section_holds_the_flat_world_layers() -> None:
    data = bytes([CODEC.packet_id(State.PLAY, CLIENTBOUND, CHUNK)])
    data += (DATA / "vanilla-26.3-first-chunk.bin").read_bytes()
    fields = cast("dict[str, object]", CODEC.decode(State.PLAY, CLIENTBOUND, data).fields)
    bottom = cast("list[dict[str, object]]", fields["sections"])[0]
    states = BLOCK_STATES.values(cast("dict[str, object]", bottom["block_states"]))
    # bedrock, two layers of dirt, grass, then air: one layer is 256 entries, y slowest
    assert states == (88,) * 256 + (10,) * 512 + (9,) * 256 + (0,) * 3072
    assert BIOMES.values(cast("dict[str, object]", bottom["biomes"])) == (41,) * 64


# A chunk: its position, the heightmaps (a type and its longs), the sections (in one byte array),
# the block entities, the light.

NO_LIGHT = "00" * 6
"""Light that names no section: four empty bit sets and no arrays."""


def _chunk_hex(heightmaps: str = "00", sections: str = "00", block_entities: str = "00") -> str:
    return "00000000" + "00000000" + heightmaps + sections + block_entities + NO_LIGHT


def _chunk(**fields: object) -> dict[str, object]:
    light = {
        "sky_light_mask": b"",
        "block_light_mask": b"",
        "empty_sky_light_mask": b"",
        "empty_block_light_mask": b"",
        "sky_light_arrays": [],
        "block_light_arrays": [],
    }
    empty = {"heightmaps": [], "sections": [], "block_entities": []}
    return {"chunk_x": 0, "chunk_z": 0, **empty, **fields, "light": light}


AIR_SECTION_HEX = "0000" + "0000" + "0000" + "0029"
"""A section of air: no blocks, no fluid, a single air state and a single plains biome."""
AIR_SECTION = {"block_count": 0, "fluid_count": 0, "block_states": AIR, "biomes": PLAINS}


def test_a_heightmap_of_a_type_the_client_does_not_know_is_kept_as_sent() -> None:
    # The client reads an unknown type as 0 (`ByIdMap.continuous`, ZERO); the codec keeps the id.
    round_trip(
        CHUNK,
        _chunk(heightmaps=[{"type": 9, "data": [1, -1]}]),
        _chunk_hex(heightmaps="01" + "09" + "02" + "0000000000000001" + "ff" * 8),
    )


def test_the_sections_are_read_to_the_end_of_their_byte_array() -> None:
    round_trip(
        CHUNK,
        _chunk(sections=[AIR_SECTION, AIR_SECTION]),
        _chunk_hex(sections="10" + AIR_SECTION_HEX * 2),
    )


def test_a_section_cut_short_by_the_end_of_the_byte_array_is_refused() -> None:
    error = decode_error(CHUNK, _chunk_hex(sections="0b" + AIR_SECTION_HEX + "000000"))
    assert "sections: 1" in error


def test_a_sections_byte_array_over_2097152_bytes_is_refused() -> None:
    assert "2097153" in decode_error(CHUNK, _chunk_hex(sections="81808001"))


def test_a_block_entity_is_its_position_type_and_tag() -> None:
    # x 3 and z 5 in one byte (0x35), y -60, type 7; the tag a compound, or TAG_End for none.
    round_trip(
        CHUNK,
        _chunk(
            block_entities=[
                {"x": 3, "z": 5, "y": -60, "type": 7, "data": b"\x0a\x00"},
                {"x": 15, "z": 0, "y": 300, "type": 0, "data": None},
            ]
        ),
        _chunk_hex(block_entities="02" + "35ffc4070a00" + "f0012c0000"),
    )


def test_a_block_entity_tag_that_is_not_a_compound_is_refused() -> None:
    error = decode_error(CHUNK, _chunk_hex(block_entities="01" + "35ffc407" + "0100"))
    assert "block_entities: 0: data" in error


@pytest.mark.parametrize(
    "entity",
    [
        {"x": 16, "z": 0, "y": 0, "type": 0, "data": None},
        {"x": 0, "z": -1, "y": 0, "type": 0, "data": None},
        {"x": 0, "z": 0, "y": 0, "type": 0, "data": b"\x01\x00"},
        {"x": 0, "z": 0, "y": 0, "type": 0},
    ],
    ids=["x past 15", "z below 0", "a tag that is not a compound", "no data"],
)
def test_a_block_entity_that_cannot_be_written_is_refused(entity: dict[str, object]) -> None:
    assert "block_entities: 0" in encode_error(CHUNK, _chunk(block_entities=[entity]))


# Paletted containers: the bits per entry sent decide the palette and how wide the entries are
# (`Strategy.getConfigurationForBitCount`); the entries are packed into Longs, never split
# across two, and the number of Longs is fixed by that width (no length is sent).


def _read(container: PalettedContainer, hex_data: str) -> dict[str, object]:
    reader = Reader(bytes.fromhex(hex_data))
    value = container.read(reader)
    reader.expect_end()
    return value


def _written(container: PalettedContainer, value: object) -> str:
    writer = Writer()
    container.write(writer, value)
    return writer.to_bytes().hex()


@pytest.mark.parametrize(
    ("container", "bits", "palette", "longs"),
    [
        (BLOCK_STATES, 1, "0100", 256),  # a list palette, 4 bits per entry whatever is sent
        (BLOCK_STATES, 4, "020001", 256),
        (BLOCK_STATES, 5, "03000102", 342),  # a hash palette, that many bits: 12 to a Long
        (BLOCK_STATES, 8, "0100", 512),
        (BLOCK_STATES, 9, "", 1024),  # the global palette: 16 bits, for 35,723 states
        (BLOCK_STATES, 15, "", 1024),
        (BLOCK_STATES, -1, "", 1024),  # read as a signed Byte: any bits from 9 up, or below 0
        (BIOMES, 1, "0100", 1),  # a list palette, that many bits
        (BIOMES, 3, "0100", 4),  # 21 to a Long
        (BIOMES, 4, "", 4),  # the global palette, read at the bits sent
        (BIOMES, 7, "", 8),
    ],
)
def test_a_container_reads_as_many_longs_as_its_width_needs(
    container: PalettedContainer, bits: int, palette: str, longs: int
) -> None:
    hex_data = f"{bits & 0xFF:02x}" + palette + "01" * 8 * longs
    value = _read(container, hex_data)
    assert value["bits"] == bits
    assert value["data"] == b"\x01" * 8 * longs
    assert _written(container, value) == hex_data


def test_a_single_value_container_is_one_id_and_no_longs() -> None:
    assert _read(BLOCK_STATES, "0001") == {"bits": 0, "palette": 1, "data": b""}
    assert _read(BIOMES, "0029") == PLAINS


def test_a_list_or_hash_palette_is_its_ids_and_the_global_palette_none() -> None:
    assert _read(BLOCK_STATES, "05" + "020203" + "00" * 8 * 342)["palette"] == [2, 3]
    assert _read(BLOCK_STATES, "10" + "00" * 8 * 1024)["palette"] is None


def test_a_block_state_past_the_last_of_26_3_is_refused_in_a_palette() -> None:
    # The client looks each palette id up with `byIdOrThrow`; 26.3 has states 0 to 35,722.
    assert _read(BLOCK_STATES, "00" + "8a9702")["palette"] == 35_722
    with pytest.raises(WireError, match="35723"):
        _read(BLOCK_STATES, "00" + "8b9702")
    with pytest.raises(WireError, match="35723"):
        _read(BLOCK_STATES, "04" + "01" + "8b9702" + "00" * 8 * 256)


def test_a_list_palette_holds_at_most_two_to_the_bits_ids() -> None:
    # `LinearPalette` keeps its ids in an array of 1 << bits.
    with pytest.raises(WireError, match="17"):
        _read(BLOCK_STATES, "04" + "11" + "00" * 17 + "00" * 8 * 256)
    with pytest.raises(WireError, match="5"):
        _read(BIOMES, "02" + "05" + "00" * 5 + "00" * 8 * 2)
    assert _read(BLOCK_STATES, "05" + "11" + "00" * 17 + "00" * 8 * 342)["palette"] == [0] * 17


@pytest.mark.parametrize("bits", [-1, 65], ids=["below 0", "past 64"])
def test_a_direct_biome_container_too_wide_to_read_is_refused(bits: int) -> None:
    with pytest.raises(WireError, match=f"direct biome container of {bits} bits"):
        _read(BIOMES, f"{bits & 0xFF:02x}" + "00" * 8)


@pytest.mark.parametrize(
    "value",
    [
        {"bits": 0, "palette": [1], "data": b""},
        {"bits": 4, "palette": 1, "data": bytes(2048)},
        {"bits": 16, "palette": [], "data": bytes(8192)},
        {"bits": 4, "palette": [1], "data": bytes(2040)},
        {"bits": 0, "palette": 1, "data": bytes(8)},
        {"bits": 4, "palette": [1] * 17, "data": bytes(2048)},
        {"bits": 0, "palette": 35_723, "data": b""},
        {"bits": 128, "palette": None, "data": bytes(8192)},
        {"bits": 0, "palette": 1},
    ],
    ids=[
        "a list for a single value",
        "one id for a list",
        "a list for the global palette",
        "too few longs",
        "longs for a single value",
        "a list too long",
        "a state past the last",
        "bits past a Byte",
        "no data",
    ],
)
def test_a_container_that_cannot_be_written_is_refused(value: dict[str, object]) -> None:
    with pytest.raises(WireError):
        _written(BLOCK_STATES, value)


def test_the_values_of_a_container_are_its_palette_ids_entry_by_entry() -> None:
    # Two bits sent: a list palette at 4 bits per entry, 16 entries to a Long, the first in
    # the lowest bits. Entry 0 is palette index 1, entry 1 index 0, the rest 0.
    value = _read(BLOCK_STATES, "02" + "020709" + "0000000000000001" + "00" * 8 * 255)
    assert BLOCK_STATES.values(value) == (9, 7) + (7,) * 4094


def test_the_values_of_a_global_container_are_its_entries() -> None:
    value = _read(BIOMES, "07" + "0000000000000081" + "00" * 8 * 7)  # 7 bits: 9 to a Long
    assert BIOMES.values(value) == (1, 1) + (0,) * 62


def test_an_entry_past_the_palette_has_no_value() -> None:
    # The client reads it and fails only when it looks the entry up (`valueFor`).
    value = _read(BLOCK_STATES, "02" + "0107" + "0000000000000001" + "00" * 8 * 255)
    assert BLOCK_STATES.values(value)[:2] == (None, 7)


# Chunk biomes: biomes alone for some chunks, each a position and every section's biome container.


def test_chunks_biomes_is_each_chunk_and_its_sections_biomes() -> None:
    round_trip(
        CHUNKS_BIOMES,
        {"chunk_biome_data": [{"chunk_z": 1, "chunk_x": -1, "biomes": [PLAINS, PLAINS]}]},
        "01" + "00000001ffffffff" + "04" + "0029" * 2,
    )
