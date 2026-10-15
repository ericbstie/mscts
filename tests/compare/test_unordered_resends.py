"""A run of resends for different entities is compared by entity, not by arrival (#320).

At the end of each tick vanilla sends what changed about each tracked entity (its data,
velocity, attributes, position and head) in the hash order of the entities' raw ids, which
differ between Instances. The client applies each resend to the entity it names, so only the
resends of each entity, in their order, matter. The entities are named and numbered as every
Comparison does (#21).
"""

from mscts.codec.packets import Packet
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, TICK_MARK, compare
from mscts.transcript import Transcript
from tests.compare.build import packet, transcript

KIND = 1
"""An entity type id: not the player's, so an entity spawned before a window is named by it."""


def add_entity(entity_id: int, x: float) -> Packet:
    """An `add_entity` of an entity at `x`."""
    return packet(
        "minecraft:add_entity",
        fields={"entity_id": entity_id, "type": KIND, "x": x, "y": -60.0, "z": 0.5},
    )


def data(entity_id: int, value: int = 1) -> Packet:
    """A `set_entity_data` of `entity_id` with one entry, `value`."""
    return packet(
        "minecraft:set_entity_data",
        fields={"entity_id": entity_id, "entries": [{"index": 0, "serializer": 0, "value": value}]},
    )


def motion(entity_id: int, y: float) -> Packet:
    """A `set_entity_motion` of `entity_id`, moving at `y` up."""
    return packet(
        "minecraft:set_entity_motion",
        fields={"entity_id": entity_id, "velocity": {"x": 0.0, "y": y, "z": 0.0}},
    )


def block() -> Packet:
    return packet("minecraft:block_update", b"\x01")


def _diff(reference: Transcript, candidate: Transcript) -> list[tuple[str, str | None]]:
    divergences = compare(reference, candidate, []).divergences
    return [(d.kind, d.path) for d in divergences]


def _play(*packets: Packet) -> Transcript:
    return transcript(*(("alice", each) for each in packets))


def test_resends_of_different_entities_in_another_order_are_no_difference() -> None:
    # The Candidate numbers its entities 5 and 9 where vanilla has 100 and 200.
    reference = _play(add_entity(100, 0.5), add_entity(200, 1.5), data(100), motion(200, 0.2))
    candidate = _play(add_entity(5, 0.5), add_entity(9, 1.5), motion(9, 0.2), data(5))
    assert _diff(reference, candidate) == []


def test_a_resend_only_one_side_sent_is_a_difference_that_names_it() -> None:
    reference = _play(add_entity(100, 0.5), add_entity(200, 1.5), data(200, 3), data(100))
    candidate = _play(add_entity(5, 0.5), add_entity(9, 1.5), data(5))
    divergences = compare(reference, candidate, []).divergences
    assert [(d.kind, d.reference) for d in divergences] == [
        (
            "missing",
            {"entity_id": "#2", "entries": [{"index": 0, "serializer": 0, "value": 3}]},
        )
    ]


def test_resends_of_one_entity_keep_their_order() -> None:
    reference = _play(add_entity(100, 0.5), motion(100, 0.1), motion(100, 0.2))
    candidate = _play(add_entity(5, 0.5), motion(5, 0.2), motion(5, 0.1))
    assert _diff(reference, candidate) == [
        ("field", "velocity.y"),
        ("field", "velocity.y"),
    ]


def test_another_packet_ends_a_run() -> None:
    reference = _play(add_entity(100, 0.5), add_entity(200, 1.5), data(100), block(), data(200))
    candidate = _play(add_entity(5, 0.5), add_entity(9, 1.5), data(9), block(), data(5))
    assert _diff(reference, candidate) == [("field", "entity_id"), ("field", "entity_id")]


def test_entities_spawned_before_the_window_are_ordered_by_their_names() -> None:
    reference = transcript(
        ("alice", add_entity(100, 1.5)),
        ("alice", add_entity(200, 0.5)),
        OBSERVE_OPEN,
        ("alice", data(200)),
        ("alice", data(100, 2)),
        OBSERVE_CLOSE,
    )
    candidate = transcript(
        ("alice", add_entity(5, 1.5)),
        ("alice", add_entity(9, 0.5)),
        OBSERVE_OPEN,
        ("alice", data(5, 2)),
        ("alice", data(9)),
        OBSERVE_CLOSE,
    )
    assert _diff(reference, candidate) == []


def test_each_resend_keeps_its_own_tick() -> None:
    reference = transcript(
        ("alice", add_entity(100, 0.5)),
        ("alice", add_entity(200, 1.5)),
        OBSERVE_OPEN,
        ("alice", data(200)),
        f"{TICK_MARK}1",
        ("alice", data(100)),
        f"{TICK_MARK}2",
        OBSERVE_CLOSE,
    )
    candidate = transcript(
        ("alice", add_entity(5, 0.5)),
        ("alice", add_entity(9, 1.5)),
        OBSERVE_OPEN,
        ("alice", data(9)),
        ("alice", data(5)),
        f"{TICK_MARK}1",
        f"{TICK_MARK}2",
        OBSERVE_CLOSE,
    )
    assert _diff(reference, candidate) == [("field", "(tick)")]


def test_an_entity_first_heard_of_in_the_run_keeps_its_place() -> None:
    # Its number is the order it arrives in, so the run cannot be sorted by it.
    reference = _play(data(100, 1), data(200, 2))
    candidate = _play(data(9, 2), data(5, 1))
    assert _diff(reference, candidate) == [
        ("field", "entries[0].value"),
        ("field", "entries[0].value"),
    ]
