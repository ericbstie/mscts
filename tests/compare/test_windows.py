"""Observation windows: a Group that has one compares only the play packets inside it."""

from dataclasses import replace

import pytest

from mscts.codec.packets import Packet, State
from mscts.compare import (
    HEARTBEAT,
    HEARTBEAT_PAYLOADS,
    OBSERVE_CLOSE,
    OBSERVE_NO_PLAY,
    OBSERVE_OPEN,
    Outcome,
    compare,
)
from mscts.transcript import Transcript
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


def test_a_close_mark_that_names_a_bot_closes_the_window_for_that_bot_only() -> None:
    # #117: each Bot's window ends at its own barrier, so bob's later packet is inside his
    # window and outside alice's.
    def play(state: int) -> Transcript:
        return transcript(
            OPEN,
            f"{CLOSE} alice",
            ("alice", block(state)),
            ("bob", block(state)),
            f"{CLOSE} bob",
        )

    verdict = compare(play(1), play(2), [])

    assert [d.bot for d in verdict.divergences] == ["bob"], verdict


def test_a_bot_with_no_close_mark_of_its_own_is_closed_by_the_unnamed_one() -> None:
    # Review of #179, HIGH 2: carol joined after the window, so it has no close Mark of its
    # own; the unnamed one stamped after the Bots' own closes ends her window.
    def play(state: int) -> Transcript:
        return transcript(
            OPEN, ("alice", block(1)), f"{CLOSE} alice", CLOSE, ("carol", block(state))
        )

    verdict = compare(play(1), play(2), [])

    assert verdict.divergences == (), verdict


def test_a_bots_own_close_mark_wins_over_an_earlier_unnamed_one() -> None:
    def play(state: int) -> Transcript:
        return transcript(OPEN, CLOSE, ("alice", block(state)), f"{CLOSE} alice")

    verdict = compare(play(1), play(2), [])

    assert [d.bot for d in verdict.divergences] == ["alice"], verdict


@pytest.mark.parametrize("close", [f"{CLOSE} alice", CLOSE])
def test_the_first_of_two_close_marks_of_a_kind_ends_the_window(close: str) -> None:
    def play(state: int) -> Transcript:
        return transcript(OPEN, ("alice", block(1)), close, ("alice", block(state)), close)

    verdict = compare(play(1), play(2), [])

    assert verdict.divergences == (), verdict


def test_each_barrier_window_closes_at_its_own_close_marks() -> None:
    # Review of #179, R8: a Bot's close Mark from one window must not close the next.
    def play(between: int, inside: int) -> Transcript:
        return transcript(
            OPEN,
            ("alice", block(1)),
            f"{CLOSE} alice",
            CLOSE,
            ("alice", block(between)),
            OPEN,
            ("alice", block(inside)),
            f"{CLOSE} alice",
            CLOSE,
            ("alice", block(between)),
        )

    assert compare(play(1, 1), play(2, 1), []).divergences == ()
    assert [d.bot for d in compare(play(1, 1), play(1, 2), []).divergences] == ["alice"]


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


PLAYER = bytes(range(16))
"""A player's UUID, as `player_info_update` writes it in each entry."""


def player_info(actions: int, *values: int) -> Packet:
    """A `player_info_update` with the `actions` byte and one entry for PLAYER of `values`."""
    return packet("minecraft:player_info_update", bytes([actions, 1, *PLAYER, *values]))


LATENCY = 0x10
"""The actions byte of UPDATE_LATENCY alone (`PlayerList.tick`, every 601 ticks)."""


def test_a_latency_only_player_info_update_inside_the_window_is_not_compared() -> None:
    verdict = compare(
        transcript(OPEN, ("alice", player_info(LATENCY, 3)), ("alice", block(1)), CLOSE),
        transcript(OPEN, ("alice", block(1)), ("alice", player_info(LATENCY, 9)), CLOSE),
        [],
    )
    assert verdict.outcome is Outcome.MATCH, verdict
    assert verdict.test_cases == ("block_update",)


@pytest.mark.parametrize(
    "actions",
    [0x04, 0x14, 0x1D, 0xFF],
    ids=["game mode", "game mode and latency", "a player joining", "every action"],
)
def test_a_player_info_update_with_another_action_is_still_compared(actions: int) -> None:
    verdict = compare(
        transcript(OPEN, ("alice", player_info(actions, 1, 3)), ("alice", block(1)), CLOSE),
        transcript(OPEN, ("alice", block(1)), CLOSE),
        [],
    )
    assert [(d.kind, d.packet) for d in verdict.divergences] == [
        ("missing", "minecraft:player_info_update")
    ], verdict


def test_another_packet_that_starts_with_the_same_byte_is_still_compared() -> None:
    verdict = compare(
        transcript(OPEN, ("alice", block(LATENCY)), ("alice", chat("a")), CLOSE),
        transcript(OPEN, ("alice", chat("a")), CLOSE),
        [],
    )
    assert [(d.kind, d.packet) for d in verdict.divergences] == [
        ("missing", "minecraft:block_update")
    ], verdict


def test_every_heartbeat_payload_has_a_reason() -> None:
    assert set(HEARTBEAT_PAYLOADS) == {("minecraft:player_info_update", bytes([LATENCY]))}
    for (name, start), reason in HEARTBEAT_PAYLOADS.items():
        assert name not in HEARTBEAT, name
        assert start, name
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


def test_a_window_with_no_play_packets_takes_none_but_still_takes_the_others() -> None:
    def login(text: bytes) -> Packet:
        return packet("minecraft:login_finished", text, state=State.LOGIN)

    verdict = compare(
        transcript(opening(OBSERVE_NO_PLAY), ("alice", login(b"a")), ("alice", chat("a")), CLOSE),
        transcript(opening(OBSERVE_NO_PLAY), ("alice", login(b"b")), ("alice", chat("b")), CLOSE),
        [],
    )
    assert [d.packet for d in verdict.divergences] == ["minecraft:login_finished"], verdict


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
