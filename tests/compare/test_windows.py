"""Observation windows: a Group that has one compares only the play packets inside it."""

from dataclasses import replace

import pytest

from mscts.codec.packets import Packet, State
from mscts.compare import HEARTBEAT, OBSERVE_CLOSE, OBSERVE_OPEN, Outcome, compare
from tests.compare.build import divergence, packet, transcript

OPEN, CLOSE = OBSERVE_OPEN, OBSERVE_CLOSE


def opening(*names: str) -> str:
    """The label of the Mark that opens a window narrowed to `names`."""
    return " ".join((OPEN, *names))


def chat(text: str) -> Packet:
    return packet("minecraft:system_chat", text.encode())


def block(state: int) -> Packet:
    return packet("minecraft:block_update", bytes([state]))


def test_a_packet_outside_the_window_is_not_compared() -> None:
    verdict = compare(
        transcript(("alice", chat("before")), OPEN, ("alice", block(1)), CLOSE),
        transcript(OPEN, ("alice", block(1)), CLOSE, ("alice", chat("after"))),
        [],
    )
    assert verdict.outcome is Outcome.MATCH, verdict
    assert verdict.test_cases == ("block_update",)


def test_a_packet_inside_the_window_is_compared_and_counted_from_the_window() -> None:
    verdict = compare(
        transcript(("alice", chat("setup")), OPEN, ("alice", block(1)), CLOSE),
        transcript(("alice", chat("setup")), OPEN, ("alice", block(2)), CLOSE),
        [],
    )
    assert verdict.divergences == (
        divergence(
            "field",
            packet="minecraft:block_update",
            reference="01",
            candidate="02",
            test_case="block_update",
        ),
    )


@pytest.mark.parametrize("name", sorted(HEARTBEAT))
def test_a_heartbeat_packet_inside_the_window_is_not_compared(name: str) -> None:
    heartbeat = packet(name, b"\x07")
    verdict = compare(
        transcript(OPEN, ("alice", heartbeat), ("alice", block(1)), ("alice", heartbeat), CLOSE),
        transcript(OPEN, ("alice", block(1)), CLOSE),
        [],
    )
    assert verdict.outcome is Outcome.MATCH, verdict
    assert verdict.test_cases == ("block_update",)


def test_every_heartbeat_packet_has_a_reason() -> None:
    assert HEARTBEAT
    for name, reason in HEARTBEAT.items():
        assert name.startswith("minecraft:"), name
        assert reason.strip(), name


def test_names_narrow_the_window_to_the_packets_they_name() -> None:
    verdict = compare(
        transcript(
            opening("minecraft:block_update"), ("alice", chat("a")), ("alice", block(1)), CLOSE
        ),
        transcript(opening("minecraft:block_update"), ("alice", block(2)), CLOSE),
        [],
    )
    assert [d.packet for d in verdict.divergences] == ["minecraft:block_update"], verdict
    assert verdict.test_cases == ("block_update",)


def test_names_take_more_than_one_packet() -> None:
    narrowed = opening("minecraft:block_update", "minecraft:system_chat")
    verdict = compare(
        transcript(narrowed, ("alice", chat("a")), ("alice", block(1)), CLOSE),
        transcript(narrowed, ("alice", chat("b")), ("alice", block(1)), CLOSE),
        [],
    )
    assert [d.packet for d in verdict.divergences] == ["minecraft:system_chat"], verdict


def test_a_group_with_no_window_compares_every_packet() -> None:
    set_time = packet("minecraft:set_time", b"\x01")
    verdict = compare(
        transcript(("alice", set_time), ("alice", chat("a"))),
        transcript(("alice", chat("a"))),
        [],
    )
    assert [(d.kind, d.packet) for d in verdict.divergences] == [
        ("missing", "minecraft:set_time")
    ], verdict


@pytest.mark.parametrize("state", [State.STATUS, State.LOGIN, State.CONFIGURATION])
def test_packets_of_the_other_states_are_compared_whole(state: State) -> None:
    before = packet("test:p", b"\x01", state=state)
    verdict = compare(
        transcript(("alice", before), OPEN, ("alice", block(1)), CLOSE),
        transcript(
            ("alice", packet("test:p", b"\x02", state=state)), OPEN, ("alice", block(1)), CLOSE
        ),
        [],
    )
    assert [(d.packet, d.reference, d.candidate) for d in verdict.divergences] == [
        ("test:p", "01", "02")
    ], verdict


def test_what_is_left_out_names_no_test_case() -> None:
    field = packet("minecraft:explode", fields={"x": 1})
    verdict = compare(
        transcript(
            ("alice", field),
            OPEN,
            ("alice", packet("minecraft:keep_alive", fields={"id": 1})),
            CLOSE,
        ),
        transcript(
            ("alice", field),
            OPEN,
            ("alice", packet("minecraft:keep_alive", fields={"id": 1})),
            CLOSE,
        ),
        [],
    )
    assert verdict.outcome is Outcome.MATCH, verdict
    assert verdict.test_cases == ()


def test_packets_between_two_windows_are_not_compared() -> None:
    verdict = compare(
        transcript(
            OPEN, ("alice", block(1)), CLOSE, ("alice", chat("x")), OPEN, ("alice", block(2)), CLOSE
        ),
        transcript(OPEN, ("alice", block(1)), CLOSE, OPEN, ("alice", block(2)), CLOSE),
        [],
    )
    assert verdict.outcome is Outcome.MATCH, verdict


def test_each_window_keeps_its_own_names() -> None:
    verdict = compare(
        transcript(
            opening("minecraft:block_update"),
            ("alice", chat("a")),
            CLOSE,
            OPEN,
            ("alice", chat("b")),
            CLOSE,
        ),
        transcript(
            opening("minecraft:block_update"),
            CLOSE,
            OPEN,
            ("alice", chat("c")),
            CLOSE,
        ),
        [],
    )
    assert [(d.reference, d.candidate) for d in verdict.divergences] == [("62", "63")], verdict


def test_a_window_that_never_closed_runs_to_the_end() -> None:
    verdict = compare(
        transcript(("alice", chat("x")), OPEN, ("alice", block(1))),
        transcript(OPEN, ("alice", block(2))),
        [],
    )
    assert [(d.packet, d.reference, d.candidate) for d in verdict.divergences] == [
        ("minecraft:block_update", "01", "02")
    ], verdict


def test_each_side_is_windowed_by_its_own_marks() -> None:
    verdict = compare(
        transcript(("alice", block(9)), OPEN, ("alice", block(1)), CLOSE),
        transcript(OPEN, ("alice", block(1)), CLOSE, ("alice", block(9))),
        [],
    )
    assert verdict.outcome is Outcome.MATCH, verdict


def test_a_bot_with_packets_only_outside_the_window_is_still_present() -> None:
    verdict = compare(
        transcript(("bob", chat("x")), OPEN, ("alice", block(1)), CLOSE),
        transcript(("bob", chat("y")), OPEN, ("alice", block(1)), CLOSE),
        [],
    )
    assert verdict.outcome is Outcome.MATCH, verdict


def test_a_bot_missing_on_one_side_is_reported_even_outside_the_window() -> None:
    verdict = compare(
        transcript(("bob", chat("x")), OPEN, ("alice", block(1)), CLOSE),
        transcript(OPEN, ("alice", block(1)), CLOSE),
        [],
    )
    assert [(d.kind, d.bot) for d in verdict.divergences] == [("bot", "bob")], verdict


def test_an_open_mark_inside_a_window_starts_the_next_one() -> None:
    verdict = compare(
        transcript(
            opening("minecraft:block_update"),
            ("alice", chat("a")),
            OPEN,
            ("alice", chat("b")),
            CLOSE,
        ),
        transcript(opening("minecraft:block_update"), OPEN, ("alice", chat("c")), CLOSE),
        [],
    )
    assert [(d.reference, d.candidate) for d in verdict.divergences] == [("62", "63")], verdict


def test_a_packet_that_arrives_as_the_window_opens_is_inside_it() -> None:
    reference = transcript(OPEN, ("alice", block(1)), CLOSE)
    candidate = transcript(OPEN, ("alice", block(2)), CLOSE)
    for side in (reference, candidate):
        side.marks[0] = replace(side.marks[0], t_ns=side.events[0].t_ns)
        side.marks[1] = replace(side.marks[1], t_ns=side.events[0].t_ns + 1)
    assert compare(reference, candidate, []).outcome is Outcome.MISMATCH


def test_a_packet_that_arrives_as_the_window_closes_is_outside_it() -> None:
    reference = transcript(OPEN, ("alice", block(1)), CLOSE)
    candidate = transcript(OPEN, ("alice", block(2)), CLOSE)
    for side in (reference, candidate):
        side.marks[1] = replace(side.marks[1], t_ns=side.events[0].t_ns)
    assert compare(reference, candidate, []).outcome is Outcome.MATCH


def test_other_marks_neither_open_nor_close_a_window() -> None:
    others = ("status:start", "observe:opened", "observe:open:x", "observe:closed")
    verdict = compare(
        transcript(("alice", chat("x")), *others, OPEN, *others, ("alice", block(1)), CLOSE),
        transcript(("alice", chat("y")), *others, OPEN, *others, ("alice", block(2)), CLOSE),
        [],
    )
    assert [(d.packet, d.reference, d.candidate) for d in verdict.divergences] == [
        ("minecraft:block_update", "01", "02")
    ], verdict


def test_the_heartbeat_packets_are_the_clocked_ones_and_the_barrier_answer() -> None:
    assert set(HEARTBEAT) == {
        "minecraft:keep_alive",
        "minecraft:set_time",
        "minecraft:award_stats",
    }


def test_marks_are_read_in_time_order_whatever_order_they_were_recorded_in() -> None:
    reference = transcript(
        ("alice", chat("a")), OPEN, ("alice", block(1)), CLOSE, ("alice", chat("b"))
    )
    candidate = transcript(
        ("alice", chat("c")), OPEN, ("alice", block(1)), CLOSE, ("alice", chat("d"))
    )
    for side in (reference, candidate):
        side.marks.reverse()
    verdict = compare(reference, candidate, [])
    assert verdict.outcome is Outcome.MATCH, verdict
