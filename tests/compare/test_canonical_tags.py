"""Canonicalization of `update_tags`: the order of registries, and of tags, is wire-only.

The client reads both into maps (PLAN, Comparison semantics), so only which value each
name ends with matters: the last one sent. The ids in a tag's entries stay in order.
Packets are built through the Target's real Codec, in configuration and in play.
"""

import pytest

from mscts.codec.packets import Codec, Packet, State
from mscts.compare import Divergence, Observability, compare
from tests.compare.build import CLIENTBOUND, transcript

CODEC = Codec.load("26.3")
STATES = pytest.mark.parametrize("state", [State.CONFIGURATION, State.PLAY], ids=str)

type _Tags = list[tuple[str, list[tuple[str, list[int]]]]]


def update_tags(state: State, registries: _Tags) -> Packet:
    fields = {
        "tagged_registries": [
            {
                "registry": registry,
                "tags": [{"tag_name": name, "entries": entries} for name, entries in tags],
            }
            for registry, tags in registries
        ]
    }
    data = CODEC.encode(state, CLIENTBOUND, "minecraft:update_tags", fields)
    return CODEC.decode(state, CLIENTBOUND, data)


def _compare(state: State, reference: _Tags, candidate: _Tags) -> tuple[Divergence, ...]:
    return compare(
        transcript(("alice", update_tags(state, reference))),
        transcript(("alice", update_tags(state, candidate))),
        [],
    ).divergences


def _observable(divergences: tuple[Divergence, ...]) -> list[tuple[str | None, object, object]]:
    return [
        (d.path, d.reference, d.candidate)
        for d in divergences
        if d.observability is Observability.OBSERVABLE
    ]


BLOCK = ("minecraft:block", [("minecraft:climbable", [1, 2]), ("minecraft:logs", [3])])
ITEM = ("minecraft:item", [("minecraft:logs", [4, 5])])


@STATES
def test_the_order_of_registries_is_wire_only(state: State) -> None:
    divergences = _compare(state, [BLOCK, ITEM], [ITEM, BLOCK])
    assert divergences
    assert _observable(divergences) == []
    assert _observable(_compare(state, [ITEM, BLOCK], [BLOCK, ITEM])) == []


@STATES
def test_the_order_of_tags_in_a_registry_is_wire_only(state: State) -> None:
    reordered = ("minecraft:block", list(reversed(BLOCK[1])))
    divergences = _compare(state, [BLOCK], [reordered])
    assert [(d.path, d.observability) for d in divergences] == [
        ("tagged_registries[0].tags[0].entries[0]", Observability.WIRE_ONLY),
        ("tagged_registries[0].tags[0].entries[1]", Observability.WIRE_ONLY),
        ("tagged_registries[0].tags[0].tag_name", Observability.WIRE_ONLY),
        ("tagged_registries[0].tags[1].entries[0]", Observability.WIRE_ONLY),
        ("tagged_registries[0].tags[1].entries[1]", Observability.WIRE_ONLY),
        ("tagged_registries[0].tags[1].tag_name", Observability.WIRE_ONLY),
    ]


@STATES
def test_the_order_of_a_tags_entries_is_observable(state: State) -> None:
    reordered = ("minecraft:block", [("minecraft:climbable", [2, 1]), ("minecraft:logs", [3])])
    assert _observable(_compare(state, [ITEM, BLOCK], [reordered, ITEM])) == [
        ("tagged_registries[0].tags[0].entries[0]", 1, 2),
        ("tagged_registries[0].tags[0].entries[1]", 2, 1),
    ]


def test_a_reordered_packet_with_a_real_difference_reports_it_at_its_canonical_path() -> None:
    changed = ("minecraft:item", [("minecraft:logs", [4, 6])])
    assert _observable(_compare(State.CONFIGURATION, [BLOCK, ITEM], [changed, BLOCK])) == [
        ("tagged_registries[1].tags[0].entries[1]", 5, 6)
    ]


def test_a_repeated_name_keeps_its_order_since_the_last_one_wins() -> None:
    first = ("minecraft:item", [("minecraft:logs", [1])])
    last = ("minecraft:item", [("minecraft:logs", [2])])
    # The same last value for every name: wire-only.
    assert (
        _observable(_compare(State.CONFIGURATION, [first, BLOCK, last], [BLOCK, first, last])) == []
    )
    # A different last value: observable.
    assert _observable(_compare(State.CONFIGURATION, [first, last], [last, first])) != []
    one_registry = [("minecraft:block", [("a:t", [1]), ("b:t", [3]), ("a:t", [2])])]
    same_last = [("minecraft:block", [("b:t", [3]), ("a:t", [1]), ("a:t", [2])])]
    other_last = [("minecraft:block", [("a:t", [2]), ("b:t", [3]), ("a:t", [1])])]
    assert _observable(_compare(State.PLAY, one_registry, same_last)) == []
    assert _observable(_compare(State.PLAY, one_registry, other_last)) != []


def test_a_missing_registry_is_observable() -> None:
    assert _observable(_compare(State.CONFIGURATION, [BLOCK, ITEM], [ITEM])) != []
