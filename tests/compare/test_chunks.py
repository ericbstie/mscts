"""A chunk is compared as the vanilla client keeps it (#22).

The block state at each position and the biome of each 4x4x4 cell, however the server encoded
them, so another palette is network traffic only, and a different block is a gameplay difference
that names its position in the world. Heightmaps are kept by type and block entities by position,
so their order is no difference. Each light section is what the client applies: an array, an
empty section, or nothing, by the rules docs/research/2026-10-02-chunks-light.md found. Packets
are built through the Target's real Codec, or are what vanilla and Pumpkin sent.
"""

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import pytest

from mscts.codec.packets import Codec, Packet, State
from mscts.codec.wire import Writer
from mscts.compare import UNORDERED, Divergence, Observability, Verdict, compare
from tests.compare.build import CLIENTBOUND, divergence, packet, transcript

CODEC = Codec.load("26.3")
CHUNK = "minecraft:level_chunk_with_light"
RECORDED = Path(__file__).resolve().parents[1] / "codec" / "schemas" / "data"

AIR, STONE = 0, 1
FLAT_LAYERS = (88, 10, 10, 9)  # the flat world's block states at y = -64 .. -61
PLAINS = 41
FLAT = [state for state in FLAT_LAYERS for _ in range(256)] + [AIR] * (4096 - 1024)
"""The flat world's lowest section, entry by entry: y slowest, then z, then x."""


def _packed(indices: Sequence[int], width: int) -> bytes:
    """Entries of `width` bits in big-endian Longs, lowest bits first, none split across two."""
    per_long = 64 // width
    data = b""
    for start in range(0, len(indices), per_long):
        word = 0
        for offset, index in enumerate(indices[start : start + per_long]):
            word |= index << (offset * width)
        data += word.to_bytes(8, "big")
    return data


def single(value: int) -> dict[str, object]:
    return {"bits": 0, "palette": value, "data": b""}


def paletted(
    values: Sequence[int], palette: list[int], *, bits: int, width: int
) -> dict[str, object]:
    """A list or hash palette container: `bits` sent, the entries packed at `width` bits."""
    indices = [palette.index(value) for value in values]
    return {"bits": bits, "palette": palette, "data": _packed(indices, width)}


def direct(values: Sequence[int], *, bits: int) -> dict[str, object]:
    return {"bits": bits, "palette": None, "data": _packed(values, bits)}


def section(
    blocks: dict[str, object], *, block_count: int, biomes: dict[str, object] | None = None
) -> dict[str, object]:
    return {
        "block_count": block_count,
        "fluid_count": 0,
        "block_states": blocks,
        "biomes": single(PLAINS) if biomes is None else biomes,
    }


def overworld(
    bottom: dict[str, object], *, biomes: dict[str, object] | None = None
) -> list[dict[str, object]]:
    """The 24 sections of an overworld chunk: `bottom`, then 23 of air."""
    air = [section(single(AIR), block_count=0) for _ in range(23)]
    return [section(bottom, block_count=1024, biomes=biomes), *air]


FLAT_BOTTOM = paletted(FLAT, [88, 10, 9, 0], bits=4, width=4)

EMPTY = "empty"
FULL, DARK = b"\xff" * 2048, bytes(2048)  # every light level 15, or 0
type _Layer = Mapping[int, bytes | str]


def _bit_set(indices: Iterable[int]) -> bytes:
    """`BitSet.toByteArray()`: bit `i` is bit `i % 8` of byte `i // 8`, no trailing zero byte."""
    number = sum(1 << index for index in set(indices))
    return number.to_bytes((number.bit_length() + 7) // 8, "little")


def light(sky: _Layer | None = None, block: _Layer | None = None) -> dict[str, object]:
    """Light data sending each light section of `sky` and `block` as an array, or EMPTY.

    Light section 0 is the one below the world; the others are not sent.
    """
    fields: dict[str, object] = {}
    for name, layer in (("sky", sky or {}), ("block", block or {})):
        fields[f"{name}_light_mask"] = _bit_set(i for i, v in layer.items() if isinstance(v, bytes))
        fields[f"empty_{name}_light_mask"] = _bit_set(i for i, v in layer.items() if v == EMPTY)
        fields[f"{name}_light_arrays"] = [
            v for _, v in sorted(layer.items()) if isinstance(v, bytes)
        ]
    return fields


def chunk(
    sections: list[dict[str, object]] | None = None,
    *,
    at: tuple[int, int] = (0, 0),
    heightmaps: list[dict[str, object]] | None = None,
    block_entities: list[dict[str, object]] | None = None,
    light_data: dict[str, object] | None = None,
) -> Packet:
    """A chunk of `sections` (the flat world's by default) at `at`, with no light unless given."""
    fields = {
        "chunk_x": at[0],
        "chunk_z": at[1],
        "heightmaps": heightmaps or [],
        "sections": overworld(FLAT_BOTTOM) if sections is None else sections,
        "block_entities": block_entities or [],
        "light": light() if light_data is None else light_data,
    }
    data = CODEC.encode(State.PLAY, CLIENTBOUND, CHUNK, fields)
    return CODEC.decode(State.PLAY, CLIENTBOUND, data)


def _verdict(reference: Packet, candidate: Packet) -> Verdict:
    return compare(transcript(("alice", reference)), transcript(("alice", candidate)), [])


def _gameplay(path: str, reference: str, candidate: str, test_case: str) -> Divergence:
    return divergence(
        "field",
        packet=CHUNK,
        path=path,
        reference=reference,
        candidate=candidate,
        test_case=f"level_chunk_with_light.{test_case}",
    )


@pytest.mark.parametrize(
    "bottom",
    [
        paletted(FLAT, [0, 9, 10, 88], bits=4, width=4),
        paletted(FLAT, [88, 10, 9, 0], bits=2, width=4),
        paletted(FLAT, [9, 88, 0, 10], bits=5, width=5),
        direct(FLAT, bits=16),
    ],
    ids=["another palette order", "fewer bits sent", "a hash palette", "the global palette"],
)
def test_the_same_blocks_under_another_palette_are_network_traffic_only(
    bottom: dict[str, object],
) -> None:
    verdict = _verdict(chunk(overworld(FLAT_BOTTOM)), chunk(overworld(bottom)))

    assert verdict.divergences
    assert verdict.gameplay == ()
    assert {str(d.path).split(".block_states")[0] for d in verdict.divergences} == {"sections[0]"}


def test_a_section_of_one_block_as_a_palette_is_network_traffic_only() -> None:
    sections = overworld(FLAT_BOTTOM)
    sections[5] = section(paletted([AIR] * 4096, [AIR], bits=4, width=4), block_count=0)

    verdict = _verdict(chunk(overworld(FLAT_BOTTOM)), chunk(sections))

    assert verdict.divergences
    assert verdict.gameplay == ()


def _with(states: dict[tuple[int, int, int], int]) -> list[int]:
    """The flat world's lowest section with the block at each section-relative x y z replaced."""
    values = list(FLAT)
    for (x, y, z), state in states.items():
        values[(y << 8) | (z << 4) | x] = state
    return values


PALETTE = [88, 10, 9, 0, STONE]


def test_one_different_block_is_a_gameplay_difference_naming_its_position() -> None:
    stone = paletted(_with({(5, 2, 7): STONE}), PALETTE, bits=4, width=4)

    verdict = _verdict(
        chunk(overworld(FLAT_BOTTOM), at=(2, -1)), chunk(overworld(stone), at=(2, -1))
    )

    assert verdict.divergences == (
        _gameplay(
            "sections[0].block_states",
            "chunk 2 -1: 37 -62 -9 is 10",
            "chunk 2 -1: 37 -62 -9 is 1",
            "sections[].block_states",
        ),
    )


def test_the_first_three_positions_that_differ_are_named_and_the_rest_counted() -> None:
    changed = {(x, 3, 0): STONE for x in range(5)}
    candidate = chunk(overworld(paletted(_with(changed), PALETTE, bits=4, width=4)))

    (difference,) = _verdict(chunk(overworld(FLAT_BOTTOM)), candidate).divergences

    assert difference.reference == "chunk 0 0: 0 -61 0 is 9, 1 -61 0 is 9, 2 -61 0 is 9 and 2 more"
    assert difference.candidate == "chunk 0 0: 0 -61 0 is 1, 1 -61 0 is 1, 2 -61 0 is 1 and 2 more"


def test_a_block_in_a_higher_section_names_its_height() -> None:
    sections = overworld(FLAT_BOTTOM)
    sections[5] = section(
        paletted([STONE] + [AIR] * 4095, [AIR, STONE], bits=4, width=4), block_count=1
    )

    verdict = _verdict(chunk(overworld(FLAT_BOTTOM)), chunk(sections))

    assert [(d.path, d.reference, d.candidate) for d in verdict.gameplay] == [
        ("sections[5].block_count", 0, 1),
        ("sections[5].block_states", "chunk 0 0: 0 16 0 is 0", "chunk 0 0: 0 16 0 is 1"),
    ]


def test_swapping_the_sides_swaps_the_positions_values() -> None:
    stone = chunk(overworld(paletted(_with({(5, 2, 7): STONE}), PALETTE, bits=4, width=4)))

    (forward,) = _verdict(chunk(overworld(FLAT_BOTTOM)), stone).divergences
    (backward,) = _verdict(stone, chunk(overworld(FLAT_BOTTOM))).divergences

    assert (backward.reference, backward.candidate) == (forward.candidate, forward.reference)


def test_a_chunk_of_another_height_counts_y_from_the_worlds_bottom() -> None:
    stone = paletted(_with({(5, 2, 7): STONE}), PALETTE, bits=4, width=4)
    reference = [section(FLAT_BOTTOM, block_count=1024)]

    verdict = _verdict(chunk(reference), chunk([section(stone, block_count=1024)]))

    assert [(d.reference, d.candidate) for d in verdict.divergences] == [
        (
            "chunk 0 0 (y from the world's bottom): 5 2 7 is 10",
            "chunk 0 0 (y from the world's bottom): 5 2 7 is 1",
        )
    ]


def test_an_entry_past_its_palette_is_a_difference_too() -> None:
    # The client reads it, and fails only when it looks the block up (`valueFor`).
    past = {"bits": 4, "palette": [88, 10, 9], "data": FLAT_BOTTOM["data"]}

    (difference,) = _verdict(chunk(overworld(FLAT_BOTTOM)), chunk(overworld(past))).gameplay

    assert (
        difference.reference == "chunk 0 0: 0 -60 0 is 0, 1 -60 0 is 0, 2 -60 0 is 0 and 3069 more"
    )
    assert difference.candidate == (
        "chunk 0 0: 0 -60 0 is past the palette, 1 -60 0 is past the palette, "
        "2 -60 0 is past the palette and 3069 more"
    )


def test_one_different_biome_is_a_gameplay_difference_naming_its_cell() -> None:
    cells = [PLAINS] * 64
    cells[(2 << 4) | (3 << 2) | 1] = 7  # the cell at x 1, y 2, z 3 of 4
    biomes = paletted(cells, [PLAINS, 7], bits=1, width=1)

    verdict = _verdict(chunk(overworld(FLAT_BOTTOM)), chunk(overworld(FLAT_BOTTOM, biomes=biomes)))

    assert verdict.divergences == (
        _gameplay(
            "sections[0].biomes",
            "chunk 0 0: 4 -56 12 is 41",
            "chunk 0 0: 4 -56 12 is 7",
            "sections[].biomes",
        ),
    )


def test_fields_the_codec_did_not_decode_are_compared_as_they_are() -> None:
    def odd(bits: int) -> Packet:
        sections = [{"block_states": {"bits": bits}}, "not a section"]
        return packet(CHUNK, fields={"chunk_x": 0, "chunk_z": 0, "sections": sections})

    verdict = _verdict(odd(0), odd(1))

    assert [(d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        ("sections[0].block_states.bits", 0, 1)
    ]
    assert _verdict(packet(CHUNK, fields={"sections": "none"}), packet(CHUNK, fields={})).gameplay
    # A list with an element of no known type or position keeps its order.
    odd_lists = {"heightmaps": [{"type": 5}, {"type": "?"}], "block_entities": [{"y": 1}, "?"]}
    swapped = {key: value[::-1] for key, value in odd_lists.items()}
    verdict = _verdict(packet(CHUNK, fields=odd_lists), packet(CHUNK, fields=swapped))
    assert {str(d.path).split("[")[0] for d in verdict.gameplay} == {"heightmaps", "block_entities"}


def heightmap(kind: int, *, height: int | None = None) -> dict[str, object]:
    """A heightmap of `Heightmap$Types` id `kind`: 37 Longs, each `height` (else `kind`)."""
    return {"type": kind, "data": [kind if height is None else height] * 37}


def test_the_order_of_heightmaps_is_no_difference() -> None:
    reference = chunk(heightmaps=[heightmap(4), heightmap(1), heightmap(5)])
    candidate = chunk(heightmaps=[heightmap(5), heightmap(4), heightmap(1)])

    assert _verdict(reference, candidate).divergences == ()


def test_another_heightmap_is_a_difference_at_its_sorted_path() -> None:
    changed: dict[str, object] = {"type": 4, "data": [4, 4, 4, 9] + [4] * 33}
    reference = chunk(heightmaps=[heightmap(5), heightmap(4), heightmap(1)])
    candidate = chunk(heightmaps=[heightmap(1), changed, heightmap(5)])

    verdict = _verdict(reference, candidate)

    assert [(d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        ("heightmaps[1].data[3]", 4, 9)
    ]


def test_a_heightmap_type_the_client_does_not_know_sorts_as_the_one_it_reads() -> None:
    # The client reads an id it does not know as WORLD_SURFACE_WG (0), and keeps the last of a
    # type sent twice: so these two differ.
    unknown, known = heightmap(7, height=1), heightmap(0, height=2)

    verdict = _verdict(chunk(heightmaps=[unknown, known]), chunk(heightmaps=[known, unknown]))

    assert verdict.gameplay


def block_entity(x: int, y: int, z: int, *, kind: int = 7) -> dict[str, object]:
    return {"x": x, "z": z, "y": y, "type": kind, "data": None}


def test_the_order_of_block_entities_at_different_positions_is_no_difference() -> None:
    a, b, c = block_entity(1, -60, 2), block_entity(3, -61, 0), block_entity(0, -60, 9)

    verdict = _verdict(chunk(block_entities=[a, b, c]), chunk(block_entities=[c, a, b]))

    assert verdict.divergences == ()


def test_block_entities_at_one_position_keep_their_order() -> None:
    # The client loads each in turn, so the last one sent ends up loaded last.
    first, second = block_entity(1, -60, 2, kind=7), block_entity(1, -60, 2, kind=8)

    verdict = _verdict(chunk(block_entities=[first, second]), chunk(block_entities=[second, first]))

    assert verdict.gameplay


def test_heightmaps_and_block_entities_are_compared_sorted_with_their_reason() -> None:
    assert "EnumMap" in UNORDERED[CHUNK]
    assert "BlockPos" in UNORDERED[CHUNK]


def test_the_same_biomes_under_another_palette_are_network_traffic_only() -> None:
    biomes = paletted([PLAINS] * 64, [PLAINS], bits=2, width=2)

    verdict = _verdict(chunk(overworld(FLAT_BOTTOM)), chunk(overworld(FLAT_BOTTOM, biomes=biomes)))

    assert verdict.divergences
    assert verdict.gameplay == ()


# Light. Light section i is world section i - 1: in a 24-section chunk, light section 1 holds
# y -64 to -49.


def _lit(sky: _Layer | None = None, block: _Layer | None = None) -> Packet:
    return chunk(light_data=light(sky, block))


def _network_traffic_only(verdict: Verdict) -> bool:
    return bool(verdict.divergences) and verdict.gameplay == ()


def test_block_light_empty_and_an_array_of_zeros_are_network_traffic_only() -> None:
    # No client code tells an empty DataLayer from one of zeros for block light.
    assert _network_traffic_only(_verdict(_lit(block={1: EMPTY}), _lit(block={1: DARK})))


def test_sky_light_below_the_world_empty_and_an_array_of_zeros_are_network_traffic_only() -> None:
    # What two vanilla Instances sent in #30. The client never fills light section 0 with sky.
    reference = _lit(sky={0: EMPTY, 1: FULL, 2: FULL})
    candidate = _lit(sky={0: DARK, 1: FULL, 2: FULL})

    assert _network_traffic_only(_verdict(reference, candidate))


def test_sky_light_in_the_world_empty_and_an_array_of_zeros_differ_in_gameplay() -> None:
    # SkyLightEngine.setLightEnabled fills an empty stored sky section with 15 the next time
    # the client applies the chunk's light; an array of zeros stays dark.
    verdict = _verdict(_lit(sky={2: EMPTY}), _lit(sky={2: DARK}))

    assert verdict.divergences == (
        _gameplay(
            "light.sky[2]",
            "chunk 0 0, y -48 to -33: empty",
            "chunk 0 0, y -48 to -33: all 0",
            "light.sky[]",
        ),
    )


def test_a_light_section_not_sent_differs_from_an_empty_one() -> None:
    # The client keeps the light it had for a section neither mask names.
    verdict = _verdict(_lit(block={3: EMPTY}), _lit())

    assert verdict.divergences == (
        _gameplay(
            "light.block[3]",
            "chunk 0 0, y -32 to -17: all 0",
            "chunk 0 0, y -32 to -17: not sent",
            "light.block[]",
        ),
    )


def test_the_mask_wins_over_the_empty_mask() -> None:
    reference = light(sky={1: FULL})
    candidate = {**reference, "empty_sky_light_mask": _bit_set([1])}

    verdict = _verdict(chunk(light_data=reference), chunk(light_data=candidate))

    assert [(d.path, d.observability) for d in verdict.divergences] == [
        ("light.empty_sky_light_mask", Observability.NETWORK_TRAFFIC)
    ]


def test_bits_past_the_light_sections_and_arrays_past_the_mask_are_never_read() -> None:
    # 24 sections have 26 light sections, 0 to 25.
    reference = light(sky={1: FULL})
    candidate = {
        **reference,
        "sky_light_mask": _bit_set([1, 26]),
        "empty_block_light_mask": _bit_set([30]),
        "sky_light_arrays": [FULL, DARK, DARK],
    }

    assert _network_traffic_only(_verdict(chunk(light_data=reference), chunk(light_data=candidate)))


def test_a_different_light_level_names_its_position() -> None:
    changed = bytearray(FULL)
    changed[((4 << 8) | (4 << 4) | 3) >> 1] = 0x0F  # x 3, y 4, z 4: an odd entry, the high bits

    verdict = _verdict(_lit(sky={1: FULL}), _lit(sky={1: bytes(changed)}))

    assert verdict.divergences == (
        _gameplay(
            "light.sky[1]",
            "chunk 0 0: 3 -60 4 is 15",
            "chunk 0 0: 3 -60 4 is 0",
            "light.sky[]",
        ),
    )


def test_light_of_another_kind_is_summed_up() -> None:
    levels = bytes(range(16)) * 128  # levels 0 to 15

    verdict = _verdict(_lit(block={4: levels}), _lit(sky={4: DARK}))

    assert [(d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        (
            "light.block[4]",
            "chunk 0 0, y -16 to -1: levels 0 to 15",
            "chunk 0 0, y -16 to -1: not sent",
        ),
        ("light.sky[4]", "chunk 0 0, y -16 to -1: not sent", "chunk 0 0, y -16 to -1: all 0"),
    ]


@pytest.mark.parametrize(
    ("arrays", "shown"),
    [([], "no array left"), ([b"\xff" * 2047], "an array of 2047 bytes")],
    ids=["too few arrays", "an array of another size"],
)
def test_light_the_client_cannot_read_is_a_value_of_its_own(
    arrays: list[bytes], shown: str
) -> None:
    # The client fails: its iterator runs out, or DataLayer refuses an array not 2048 bytes long.
    reference = light(sky={1: FULL})
    candidate = {**reference, "sky_light_arrays": arrays}

    verdict = _verdict(chunk(light_data=reference), chunk(light_data=candidate))

    assert [(d.path, d.candidate) for d in verdict.gameplay] == [
        ("light.sky[1]", f"chunk 0 0, y -64 to -49: {shown}")
    ]


def _recorded(server: str) -> Packet:
    payload = (RECORDED / f"{server}-26.3-first-chunk.bin").read_bytes()
    packet_id = CODEC.packet_id(State.PLAY, CLIENTBOUND, CHUNK)
    return CODEC.decode(State.PLAY, CLIENTBOUND, Writer().var_int(packet_id).to_bytes() + payload)


def test_pumpkins_light_differs_in_gameplay_where_vanilla_sends_none() -> None:
    # The first chunks of the 2026-09-30 joins have the same blocks, biomes and heightmaps.
    # Vanilla sends sky arrays for light sections 1 and 2 and names no section above them;
    # Pumpkin sends 15s up to the top. The client keeps what it had where vanilla names none,
    # so that is a gameplay difference, never a canonical rule.
    verdict = _verdict(_recorded("vanilla"), _recorded("pumpkin"))

    above = range(3, 26)
    assert {d.path for d in verdict.divergences} == {
        *(f"light.sky[{index}]" for index in above),
        *(f"light.block[{index}]" for index in above),
    }
    assert verdict.gameplay == verdict.divergences
    shown = {d.path: (d.reference, d.candidate) for d in verdict.divergences}
    assert shown["light.sky[3]"] == (
        "chunk 0 0, y -32 to -17: not sent",
        "chunk 0 0, y -32 to -17: all 15",
    )
    assert shown["light.sky[25]"] == (
        "chunk 0 0, y 320 to 335: not sent",
        "chunk 0 0, y 320 to 335: empty",
    )


def light_update(data: dict[str, object]) -> Packet:
    fields = {"chunk_x": 1, "chunk_z": 2, "data": data}
    encoded = CODEC.encode(State.PLAY, CLIENTBOUND, "minecraft:light_update", fields)
    return CODEC.decode(State.PLAY, CLIENTBOUND, encoded)


def test_a_light_update_follows_the_same_rules() -> None:
    # It has no sections to say how high the world is: y counts from the world's bottom.
    equal = _verdict(
        light_update(light(sky={0: EMPTY}, block={1: EMPTY})),
        light_update(light(sky={0: DARK}, block={1: DARK})),
    )
    differ = _verdict(light_update(light(sky={2: EMPTY})), light_update(light(sky={2: DARK})))

    assert _network_traffic_only(equal)
    assert [(d.path, d.reference, d.candidate) for d in differ.divergences] == [
        (
            "data.sky[2]",
            "chunk 1 2 (y from the world's bottom), y 16 to 31: empty",
            "chunk 1 2 (y from the world's bottom), y 16 to 31: all 0",
        )
    ]


def test_a_light_update_naming_fewer_sections_differs_only_where_the_other_names_one() -> None:
    verdict = _verdict(
        light_update(light(sky={1: FULL, 5: FULL})), light_update(light(sky={1: FULL}))
    )

    assert [d.path for d in verdict.divergences] == ["data.sky[5]"]
