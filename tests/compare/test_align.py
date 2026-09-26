"""How compare() aligns two Bot streams, and what its Divergences' indices mean."""

import itertools
from collections.abc import Sequence

from mscts.codec.packets import Packet
from mscts.compare import ABSENT, Divergence, _align, compare
from tests.compare.build import packet, transcript


def _named(*names: str) -> list[Packet]:
    return [packet(f"test:{name}") for name in names]


def _kinds(reference: list[Packet], candidate: list[Packet]) -> list[tuple[str, int, str]]:
    """(kind, index, packet) of each Divergence of alice's two streams."""
    verdict = compare(
        transcript(*(("alice", p) for p in reference)),
        transcript(*(("alice", p) for p in candidate)),
        [],
    )
    return [(d.kind, d.index, d.packet.removeprefix("test:")) for d in verdict.divergences]


def test_an_extra_packet_leaves_the_rest_matched() -> None:
    assert _kinds(_named("a", "b", "c"), _named("a", "x", "b", "c")) == [("unexpected", 1, "x")]


def test_a_lost_packet_leaves_the_rest_matched() -> None:
    assert _kinds(_named("a", "x", "b", "c"), _named("a", "b", "c")) == [("missing", 1, "x")]


def test_missing_indexes_the_reference_and_unexpected_the_candidate() -> None:
    assert _kinds(_named("a", "x", "b", "c"), _named("a", "b", "c", "y")) == [
        ("missing", 1, "x"),
        ("unexpected", 3, "y"),
    ]


def test_a_field_divergence_indexes_the_reference_stream() -> None:
    reference = [*_named("a", "x", "y"), packet("test:b", b"\x01")]
    candidate = [*_named("a"), packet("test:b", b"\x02")]
    verdict = compare(
        transcript(*(("alice", p) for p in reference)),
        transcript(*(("alice", p) for p in candidate)),
        [],
    )
    assert verdict.divergences[-1] == Divergence(
        bot="alice",
        index=3,
        kind="field",
        packet="test:b",
        path=None,
        reference="01",
        candidate="02",
    )


def test_a_repeated_packet_after_a_common_prefix_is_the_extra_one() -> None:
    assert _kinds(_named("a", "a"), _named("a")) == [("missing", 1, "a")]
    assert _kinds(_named("a"), _named("a", "a")) == [("unexpected", 1, "a")]


def test_the_common_suffix_is_matched_as_it_stands() -> None:
    # So of repeated packets, the prefix matches the earliest and the suffix the latest:
    # [a] against [b, a, a] matches the last a.
    assert _kinds(_named("a"), _named("b", "a", "a")) == [
        ("unexpected", 0, "b"),
        ("unexpected", 1, "a"),
    ]


def _longest_common_subsequence_length(
    first: Sequence[tuple[str, str]], second: Sequence[tuple[str, str]]
) -> int:
    """The textbook dynamic programme, as an oracle."""
    table = [[0] * (len(second) + 1) for _ in range(len(first) + 1)]
    for i in reversed(range(len(first))):
        for j in reversed(range(len(second))):
            table[i][j] = (
                table[i + 1][j + 1] + 1
                if first[i] == second[j]
                else max(table[i + 1][j], table[i][j + 1])
            )
    return table[0][0]


def test_every_small_alignment_is_ordered_longest_and_mirrored_by_a_swap() -> None:
    sequences = [
        [("play", name) for name in names]
        for length in range(5)
        for names in itertools.product("abc", repeat=length)
    ]
    for reference in sequences:
        for candidate in sequences:
            pairs = _align(reference, candidate)
            assert all(reference[i] == candidate[j] for i, j in pairs)
            assert all(i < k and j < m for (i, j), (k, m) in itertools.pairwise(pairs))
            assert len(pairs) == _longest_common_subsequence_length(reference, candidate)
            assert _align(candidate, reference) == [(j, i) for i, j in pairs]


def test_the_alignment_keeps_the_most_packets_matched() -> None:
    # The longest run in both is x y z, but a1..a4 are more packets. A longest-block
    # matcher (difflib) would match x y z and leave all four a's unmatched.
    reference = _named("x", "y", "z", "a1", "q", "a2", "q", "a3", "q", "a4")
    candidate = _named("a1", "a2", "a3", "a4", "x", "y", "z")
    assert _kinds(reference, candidate) == [
        ("missing", 0, "x"),
        ("missing", 1, "y"),
        ("missing", 2, "z"),
        ("missing", 4, "q"),
        ("missing", 6, "q"),
        ("missing", 8, "q"),
        ("unexpected", 4, "x"),
        ("unexpected", 5, "y"),
        ("unexpected", 6, "z"),
    ]


def test_between_matches_missing_packets_come_before_unexpected_ones() -> None:
    assert _kinds(_named("a", "x", "b"), _named("a", "y", "b")) == [
        ("missing", 1, "x"),
        ("unexpected", 1, "y"),
    ]


def test_a_tie_leaves_the_smaller_key_unmatched_whichever_side_it_is_on() -> None:
    # [x, y] and [y, x] have two longest alignments. The tie is broken on the packet
    # keys, not on which side is the reference, so swapping the sides mirrors it.
    assert _kinds(_named("x", "y"), _named("y", "x")) == [
        ("missing", 0, "x"),
        ("unexpected", 1, "x"),
    ]
    assert _kinds(_named("y", "x"), _named("x", "y")) == [
        ("unexpected", 0, "x"),
        ("missing", 1, "x"),
    ]


def test_a_long_stream_with_one_difference_aligns_around_it() -> None:
    common = [packet(f"test:p{n % 7}", bytes([n % 256])) for n in range(3000)]
    reference = [*common[:1500], packet("test:x"), *common[1500:]]
    verdict = compare(
        transcript(*(("alice", p) for p in reference)),
        transcript(*(("alice", p) for p in common)),
        [],
    )
    assert verdict.divergences == (
        Divergence(
            bot="alice",
            index=1500,
            kind="missing",
            packet="test:x",
            path=None,
            reference="",
            candidate=ABSENT,
        ),
    )
