"""`section_blocks_update.blocks` is compared sorted by position (`UNORDERED`, #320).

Vanilla sends the list in the order of a hash set of the changed positions, and another server
may send the same changes in another order. The client sets each block at its own position in
turn, so only which state each position ends with matters. Packets are built through the
Target's real Codec.
"""

from mscts.codec.packets import Codec, Packet, State
from mscts.compare import ABSENT, UNORDERED, compare
from tests.compare.build import CLIENTBOUND, transcript

CODEC = Codec.load("26.3")

type _Block = tuple[int, int, int, int]
"""A changed block: its x, y and z in the section, and its new state."""


def section_blocks_update(blocks: list[_Block]) -> Packet:
    """A `section_blocks_update` of section (0, -4, 0) with these changes, in this order."""
    data = CODEC.encode(
        State.PLAY,
        CLIENTBOUND,
        "minecraft:section_blocks_update",
        {
            "section": {"x": 0, "y": -4, "z": 0},
            "blocks": [{"x": x, "y": y, "z": z, "state": state} for x, y, z, state in blocks],
        },
    )
    return CODEC.decode(State.PLAY, CLIENTBOUND, data)


def _diff(
    reference: list[_Block], candidate: list[_Block]
) -> list[tuple[str | None, object, object]]:
    divergences = compare(
        transcript(("alice", section_blocks_update(reference))),
        transcript(("alice", section_blocks_update(candidate))),
        [],
    ).divergences
    return [(d.path, d.reference, d.candidate) for d in divergences]


LOW, MIDDLE, HIGH = (5, 0, 2, 1), (1, 0, 9, 1), (0, 3, 0, 1)
"""Three changes, in the order of their positions: y, then z, then x."""


def test_the_order_of_the_blocks_is_no_difference() -> None:
    assert _diff([LOW, MIDDLE, HIGH], [HIGH, LOW, MIDDLE]) == []
    assert _diff([MIDDLE, HIGH, LOW], [LOW, HIGH, MIDDLE]) == []


def test_a_block_only_one_side_sent_is_a_difference_that_names_it() -> None:
    assert _diff([HIGH, LOW, MIDDLE], [MIDDLE, LOW]) == [
        ("blocks[2]", {"x": 0, "y": 3, "z": 0, "state": 1}, ABSENT)
    ]


def test_another_state_is_a_difference_at_the_blocks_sorted_path() -> None:
    assert _diff([HIGH, LOW, MIDDLE], [(1, 0, 9, 7), HIGH, LOW]) == [("blocks[1].state", 1, 7)]


def test_a_repeated_position_keeps_its_order_since_the_last_one_wins() -> None:
    first, last = (5, 0, 2, 1), (5, 0, 2, 8)
    assert _diff([first, HIGH, last], [HIGH, first, last]) == []
    assert _diff([first, last], [last, first]) != []


def test_the_blocks_are_compared_sorted_with_their_reason() -> None:
    assert "setServerVerifiedBlockState" in UNORDERED["minecraft:section_blocks_update"]
