"""A chunk is compared as the vanilla client keeps it (#22).

The block state at each position and the biome of each 4x4x4 cell, however the server encoded
them, so another palette is network traffic only, and a different block is a gameplay difference
that names its position in the world (docs/research/2026-10-02-chunks-light.md). Packets are
built through the Target's real Codec.
"""

from collections.abc import Sequence

import pytest

from mscts.codec.packets import Codec, Packet, State
from mscts.compare import Divergence, Verdict, compare
from tests.compare.build import CLIENTBOUND, divergence, packet, transcript

CODEC = Codec.load("26.3")
CHUNK = "minecraft:level_chunk_with_light"

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
NO_LIGHT: dict[str, object] = {
    "sky_light_mask": b"",
    "block_light_mask": b"",
    "empty_sky_light_mask": b"",
    "empty_block_light_mask": b"",
    "sky_light_arrays": [],
    "block_light_arrays": [],
}


def chunk(sections: list[dict[str, object]], *, x: int = 0, z: int = 0) -> Packet:
    fields = {
        "chunk_x": x,
        "chunk_z": z,
        "heightmaps": [],
        "sections": sections,
        "block_entities": [],
        "light": NO_LIGHT,
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

    verdict = _verdict(chunk(overworld(FLAT_BOTTOM), x=2, z=-1), chunk(overworld(stone), x=2, z=-1))

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


def test_the_same_biomes_under_another_palette_are_network_traffic_only() -> None:
    biomes = paletted([PLAINS] * 64, [PLAINS], bits=2, width=2)

    verdict = _verdict(chunk(overworld(FLAT_BOTTOM)), chunk(overworld(FLAT_BOTTOM, biomes=biomes)))

    assert verdict.divergences
    assert verdict.gameplay == ()
