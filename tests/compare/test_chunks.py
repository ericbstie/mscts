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
from mscts.compare import ABSENT, UNORDERED, Divergence, Mask, Observability, Verdict, compare
from mscts.test_cases import TITLES
from mscts.transcript import Transcript
from tests.compare.build import CLIENTBOUND, divergence, packet, transcript

CODEC = Codec.load("26.3")
CHUNK = "minecraft:level_chunk_with_light"
CHUNK_TEST_CASE = "level_chunk_with_light"
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


def test_three_positions_that_differ_are_all_named() -> None:
    changed = {(x, 3, 0): STONE for x in range(3)}
    candidate = chunk(overworld(paletted(_with(changed), PALETTE, bits=4, width=4)))

    (difference,) = _verdict(chunk(overworld(FLAT_BOTTOM)), candidate).divergences

    assert difference.candidate == "chunk 0 0: 0 -61 0 is 1, 1 -61 0 is 1, 2 -61 0 is 1"


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


STONE_BOTTOM = paletted(_with({(5, 2, 7): STONE}), PALETTE, bits=4, width=4)
NETHER_AIR = [section(single(AIR), block_count=0) for _ in range(15)]


def test_a_chunk_as_high_as_the_nether_counts_y_from_0() -> None:
    # The nether and the end have 16 sections, from y 0.
    reference = [section(FLAT_BOTTOM, block_count=1024), *NETHER_AIR]
    candidate = [section(STONE_BOTTOM, block_count=1024), *NETHER_AIR]

    verdict = _verdict(chunk(reference), chunk(candidate))

    assert [(d.reference, d.candidate) for d in verdict.divergences] == [
        ("chunk 0 0: 5 2 7 is 10", "chunk 0 0: 5 2 7 is 1")
    ]


def test_chunks_of_two_heights_count_y_from_the_worlds_bottom() -> None:
    candidate = [section(STONE_BOTTOM, block_count=1024), *NETHER_AIR]

    verdict = _verdict(chunk(overworld(FLAT_BOTTOM)), chunk(candidate))

    shown = {d.path: (d.reference, d.candidate) for d in verdict.divergences}
    assert shown["sections[0].block_states"] == (
        "chunk 0 0 (y from the world's bottom): 5 2 7 is 10",
        "chunk 0 0 (y from the world's bottom): 5 2 7 is 1",
    )


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


def test_a_section_whose_every_entry_is_past_its_palette_names_its_positions() -> None:
    every: dict[str, object] = {"bits": 4, "palette": [AIR], "data": _packed([1] * 4096, 4)}
    sections = overworld(FLAT_BOTTOM)
    sections[1] = section(every, block_count=0)

    (difference,) = _verdict(chunk(overworld(FLAT_BOTTOM)), chunk(sections)).gameplay

    assert difference.candidate == (
        "chunk 0 0: 0 -48 0 is past the palette, 1 -48 0 is past the palette, "
        "2 -48 0 is past the palette and 4093 more"
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


def test_a_container_the_client_cannot_read_is_shown_as_it_is() -> None:
    def holding(block_states: object) -> Packet:
        sections = [{"block_states": block_states}]
        return packet(CHUNK, fields={"chunk_x": 0, "chunk_z": 0, "sections": sections})

    unreadable = {"bits": 99, "palette": None, "data": b""}  # no palette has 99 bits

    verdict = _verdict(holding(unreadable), holding(single(STONE)))

    assert [(d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        ("sections[0].block_states", unreadable, STONE)
    ]


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


# A direct biome container: the client reads it at ceillog2 of the biomes the server sent in
# configuration, whatever its bits say; the codec reads it at the bits sent.


def _registry(name: str, size: int) -> Packet:
    entries = [{"entry_id": f"minecraft:entry_{index}", "data": None} for index in range(size)]
    fields = {"registry_id": name, "entries": entries}
    encoded = CODEC.encode(State.CONFIGURATION, CLIENTBOUND, "minecraft:registry_data", fields)
    return CODEC.decode(State.CONFIGURATION, CLIENTBOUND, encoded)


def _joined(chunk_packet: Packet, *, biomes: int = 67) -> Transcript:
    """`biomes` biomes in configuration (both recorded joins sent 67), then `chunk_packet`.

    Neither another registry nor another Bot's biomes count.
    """
    return transcript(
        ("alice", _registry("minecraft:worldgen/biome", biomes)),
        ("alice", _registry("minecraft:damage_type", 100)),
        ("bob", _registry("minecraft:worldgen/biome", 100)),
        ("alice", chunk_packet),
    )


@pytest.mark.parametrize(("biomes", "bits"), [(67, 7), (64, 6)])
def test_a_direct_biome_container_of_the_width_the_client_reads_is_network_traffic_only(
    biomes: int, bits: int
) -> None:
    # Mth.ceillog2(67) = 7, Mth.ceillog2(64) = 6.
    cells = direct([PLAINS] * 64, bits=bits)
    reference = _joined(chunk(), biomes=biomes)

    verdict = compare(
        reference, _joined(chunk(overworld(FLAT_BOTTOM, biomes=cells)), biomes=biomes), []
    )

    assert verdict.divergences
    assert verdict.gameplay == ()


@pytest.mark.parametrize("bits", [8, 6])
def test_a_direct_biome_container_of_another_width_is_a_gameplay_difference(bits: int) -> None:
    cells = direct([PLAINS] * 64, bits=bits)

    verdict = compare(_joined(chunk()), _joined(chunk(overworld(FLAT_BOTTOM, biomes=cells))), [])

    data = _packed([PLAINS] * 64, bits).hex()
    assert [(d.path, d.reference, d.candidate) for d in verdict.gameplay] == [
        (
            "sections[0].biomes",
            "chunk 0 0, y -64 to -49: all 41",
            f"chunk 0 0, y -64 to -49: {bits} bits per entry where the client reads 7: {data}",
        )
    ]


# A batch: the server sends the chunks at one distance in the iteration order of a hash set, and
# the client keeps each by its position.


def _batch(*chunks: Packet) -> Transcript:
    return _played(chunks)


def test_the_chunks_of_a_batch_in_another_order_are_no_difference() -> None:
    first, second, third = (chunk(at=at) for at in ((0, 0), (-1, 0), (0, 1)))

    verdict = compare(_batch(first, second, third), _batch(third, first, second), [])

    assert verdict.divergences == ()


def _played(*items: Packet | tuple[Packet, ...]) -> Transcript:
    """The Packets in order, each tuple a batch of chunks."""
    packets: list[Packet] = []
    for item in items:
        if isinstance(item, tuple):
            start = packet("minecraft:chunk_batch_start", fields={})
            finished = packet("minecraft:chunk_batch_finished", fields={"batch_size": len(item)})
            packets.extend((start, *item, finished))
        else:
            packets.append(item)
    return transcript(*(("alice", each) for each in packets))


def test_chunks_in_a_row_are_sorted_in_or_out_of_a_batch() -> None:
    first, second, third = (chunk(at=(x, 0)) for x in range(3))

    verdict = compare(_played((first,), second, third), _played((first,), third, second), [])

    assert verdict.divergences == ()


def _at(name: str, x: int, z: int, **fields: object) -> Packet:
    """A `light_update` or `forget_level_chunk` of the chunk at x, z, through the Codec."""
    encoded = CODEC.encode(State.PLAY, CLIENTBOUND, name, {"chunk_x": x, "chunk_z": z, **fields})
    return CODEC.decode(State.PLAY, CLIENTBOUND, encoded)


START = packet("minecraft:chunk_batch_start", fields={})
LIT_A, LIT_B = (chunk(at=at, light_data=light(sky={2: DARK})) for at in ((0, 0), (1, 0)))
# Each kind of packet that changes chunk B on the client: its light, and dropping it.
CHANGES_B = [
    _at("minecraft:light_update", 1, 0, data=light(sky={2: FULL})),
    _at("minecraft:forget_level_chunk", 1, 0),
]


def _finished(size: int) -> Packet:
    return packet("minecraft:chunk_batch_finished", fields={"batch_size": size})


@pytest.mark.parametrize("change", CHANGES_B, ids=["light_update", "forget_level_chunk"])
def test_a_chunk_never_moves_across_a_packet_that_changes_it(change: Packet) -> None:
    # The client applies B, then the change, on one side; the change, then B, on the other. The
    # second ends with B's own light, or with B loaded (the ordering review of #122, probes 1, 2).
    reference = _batch_of(START, LIT_B, change, LIT_A, _finished(2))
    candidate = _batch_of(START, LIT_A, change, LIT_B, _finished(2))

    assert compare(reference, candidate, []).gameplay


def _batch_of(*packets: Packet | str) -> Transcript:
    """`packets` received by alice in order; a string is a Mark."""
    return transcript(*(each if isinstance(each, str) else ("alice", each) for each in packets))


UPDATE_A, UPDATE_B = (
    _at("minecraft:light_update", x, 0, data=light(sky={2: FULL})) for x in (0, 1)
)
FORGET_A, FORGET_B, FORGET_C = (_at("minecraft:forget_level_chunk", x, 0) for x in (0, 1, 2))


@pytest.mark.parametrize(
    ("reference", "candidate"),
    [
        ((UPDATE_A, UPDATE_B), (UPDATE_B, UPDATE_A)),
        ((FORGET_A, FORGET_B), (FORGET_B, FORGET_A)),
        ((LIT_A, UPDATE_B, FORGET_C), (FORGET_C, UPDATE_B, LIT_A)),
    ],
    ids=["light updates", "forgotten chunks", "a chunk, a light update and a forgotten chunk"],
)
def test_packets_for_different_chunks_in_a_row_are_sorted_by_position(
    reference: tuple[Packet, ...], candidate: tuple[Packet, ...]
) -> None:
    # Vanilla sends the light updates of one tick in the order of an identity hash set
    # (ServerChunkCache.chunkHoldersToBroadcast), and the client keeps light by position.
    verdict = compare(_batch_of(LIT_A, LIT_B, *reference), _batch_of(LIT_A, LIT_B, *candidate), [])

    assert verdict.divergences == ()


def test_packets_for_one_chunk_keep_their_order() -> None:
    verdict = compare(
        _batch_of(LIT_B, UPDATE_B, FORGET_B), _batch_of(LIT_B, FORGET_B, UPDATE_B), []
    )

    assert verdict.gameplay


@pytest.mark.parametrize("name", ["minecraft:light_update", "minecraft:forget_level_chunk"])
def test_a_light_update_or_forgotten_chunk_is_matched_by_its_position(name: str) -> None:
    # The verdict review of #122, probe 2: light for chunk 0 0 was shown against chunk -3 5's.
    reference = _batch_of(_at(name, 0, 0, **_light_fields(name)))
    candidate = _batch_of(_at(name, -3, 5, **_light_fields(name)))

    assert [
        (d.kind, d.reference, d.candidate) for d in compare(reference, candidate, []).divergences
    ] == [
        ("missing", "chunk 0 0", ABSENT),
        ("unexpected", ABSENT, "chunk -3 5"),
    ]


def _light_fields(name: str) -> dict[str, object]:
    return {"data": light(sky={5: FULL})} if name == "minecraft:light_update" else {}


BLOCK = packet("minecraft:block_update", fields={"pos": {"x": 1, "y": -60, "z": 0}, "state": 1})
NARROWED = "observe:open minecraft:level_chunk_with_light"


@pytest.mark.parametrize(
    ("window", "masks"),
    [(True, []), (False, [Mask("minecraft:block_update", "*", "a test")])],
    ids=["a narrowed window", "a Mask of the whole packet"],
)
def test_chunks_are_put_in_order_before_anything_is_left_out(
    *, window: bool, masks: list[Mask]
) -> None:
    # The block update between the chunks is not compared, but the client still applies it
    # between them, so they keep their order around it.
    first, second = chunk(at=(0, 0)), chunk(at=(1, 0))
    opened, closed = ((NARROWED,), ("observe:close",)) if window else ((), ())

    verdict = compare(
        _batch_of(*opened, START, first, BLOCK, second, _finished(2), *closed),
        _batch_of(*opened, START, second, BLOCK, first, _finished(2), *closed),
        masks,
    )

    assert verdict.gameplay


# Batches. Which chunks go in which batch races between two vanilla Instances (the ordering review
# of #122, finding 2): PlayerChunkSender.sendNextChunks takes the pending chunks that are ready.


def test_chunks_are_compared_by_position_across_batches() -> None:
    first, second, third, fourth = (chunk(at=(x, 0)) for x in range(4))

    verdict = compare(
        _played((first, second), (third, fourth)), _played((first, third), (second, fourth)), []
    )

    assert verdict.divergences == ()


# The client handles these without reading a chunk (javap on the 26.3 client,
# docs/research/2026-10-02-chunks-light.md), so a chunk may arrive on either side of one.
UNRELATED = [
    "minecraft:chunk_batch_start",
    "minecraft:chunk_batch_finished",
    "minecraft:keep_alive",
    "minecraft:set_time",
    "minecraft:award_stats",
    "minecraft:pong_response",
    "minecraft:bundle_delimiter",
    "minecraft:add_entity",
    "minecraft:move_entity_pos",
    "minecraft:move_entity_pos_rot",
    "minecraft:move_entity_rot",
    "minecraft:rotate_head",
    "minecraft:set_entity_motion",
    "minecraft:update_attributes",
    "minecraft:remove_entities",
]


def test_a_packet_between_batches_is_compared_after_the_chunks_around_it() -> None:
    # What two vanilla Instances sent in a join: the player's attributes between two batches,
    # after another number of chunks on each side.
    first, second, third = (chunk(at=(x, 0)) for x in range(3))
    attributes = packet("minecraft:update_attributes", fields={"entity_id": 1})

    verdict = compare(
        _played((first, second), attributes, (third,)),
        _played((first,), attributes, (second, third)),
        [],
    )

    assert [(d.kind, d.packet, d.path) for d in verdict.gameplay] == [
        ("field", "minecraft:chunk_batch_finished", "batch_size"),
        ("field", "minecraft:chunk_batch_finished", "batch_size"),
    ]


@pytest.mark.parametrize("name", UNRELATED)
def test_chunks_are_sorted_across_a_packet_whose_handling_reads_no_chunk(name: str) -> None:
    between = packet(name, fields={})

    verdict = compare(_batch_of(LIT_A, between, LIT_B), _batch_of(LIT_B, between, LIT_A), [])

    assert verdict.divergences == ()


@pytest.mark.parametrize(
    "name",
    [
        # Its handler snaps the entity, or interpolates it, by whether its chunk is loaded
        # (ClientLevel.isTickingEntity).
        "minecraft:entity_position_sync",
        "minecraft:teleport_entity",
        # A sleeping entity's position is set from the bed block there (LivingEntity.setPosToBed).
        "minecraft:set_entity_data",
        "minecraft:entity_event",
        "minecraft:block_update",
        "minecraft:chunks_biomes",
    ],
)
def test_chunks_keep_their_order_around_any_other_packet(name: str) -> None:
    between = packet(name, fields={})

    verdict = compare(_batch_of(LIT_A, between, LIT_B), _batch_of(LIT_B, between, LIT_A), [])

    assert verdict.gameplay


@pytest.mark.parametrize("change", CHANGES_B, ids=["light_update", "forget_level_chunk"])
def test_a_chunk_never_moves_across_a_packet_that_changes_it_in_another_batch(
    change: Packet,
) -> None:
    reference = _batch_of(START, LIT_B, _finished(1), change, START, LIT_A, _finished(1))
    candidate = _batch_of(START, LIT_A, _finished(1), change, START, LIT_B, _finished(1))

    assert compare(reference, candidate, []).gameplay


def test_a_chunk_only_one_side_sent_is_a_divergence_naming_its_position() -> None:
    reference = _batch(chunk(at=(0, 0)), chunk(at=(3, -2)))
    candidate = _batch(chunk(at=(1, 1)), chunk(at=(0, 0)))

    assert compare(reference, candidate, []).divergences == (
        divergence(
            "missing", index=2, packet=CHUNK, reference="chunk 3 -2", test_case=CHUNK_TEST_CASE
        ),
        divergence(
            "unexpected", index=2, packet=CHUNK, candidate="chunk 1 1", test_case=CHUNK_TEST_CASE
        ),
    )


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
    levels = DARK[:1024] + FULL[:1024]  # levels 0 and 15

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


def test_a_light_update_is_read_over_256_light_sections() -> None:
    # No level has more (DimensionType's height is at most Y_SIZE, 4064 blocks).
    read = _verdict(light_update(light()), light_update(light(sky={255: FULL})))
    never_read = _verdict(light_update(light()), light_update(light(sky={256: FULL})))

    assert [d.path for d in read.gameplay] == ["data.sky[255]"]
    assert _network_traffic_only(never_read)


def test_a_light_update_naming_fewer_sections_differs_only_where_the_other_names_one() -> None:
    verdict = _verdict(
        light_update(light(sky={1: FULL, 5: FULL})), light_update(light(sky={1: FULL}))
    )

    assert [d.path for d in verdict.divergences] == ["data.sky[5]"]


def test_the_gameplay_test_cases_of_chunks_and_light_have_titles() -> None:
    stone = paletted(_with({(5, 2, 7): STONE}), PALETTE, bits=4, width=4)
    biome = direct([PLAINS] * 63 + [PLAINS + 1], bits=7)
    verdicts = [
        _verdict(chunk(), chunk(overworld(stone, biomes=biome))),
        _verdict(_lit(sky={2: EMPTY}, block={1: FULL}), _lit(sky={2: DARK}, block={1: DARK})),
        _verdict(
            light_update(light(sky={2: EMPTY}, block={1: FULL})),
            light_update(light(sky={2: DARK}, block={1: DARK})),
        ),
        compare(_batch(chunk()), _batch(chunk(at=(1, 0))), []),
    ]

    cases = {d.test_case for verdict in verdicts for d in verdict.gameplay}

    assert cases == {name for name in TITLES if "chunk" in name or "light" in name}
