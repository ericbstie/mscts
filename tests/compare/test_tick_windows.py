"""Tick windows: a tick-exact Group compares what each Bot received on each tick."""

import pytest

from mscts.codec.packets import Packet, State
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, TICK_MARK, TICK_PATH, Outcome, compare
from mscts.transcript import Transcript
from tests.compare.build import divergence, packet, transcript

OPEN, CLOSE = OBSERVE_OPEN, OBSERVE_CLOSE


def tick(k: int, bot: str | None = None) -> str:
    """The label of the Mark that ends tick `k`, for `bot` or for every Bot."""
    return f"{TICK_MARK}{k}" if bot is None else f"{TICK_MARK}{k} {bot}"


def block(state: int) -> Packet:
    return packet("minecraft:block_update", bytes([state]))


def test_the_same_packets_on_the_same_ticks_match() -> None:
    def play() -> Transcript:
        return transcript(OPEN, ("alice", block(1)), tick(1), ("alice", block(2)), tick(2), CLOSE)

    verdict = compare(play(), play(), [])

    assert verdict.outcome is Outcome.MATCH, verdict
    assert verdict.test_cases == ("block_update",)


def test_a_packet_one_tick_late_is_a_divergence_naming_both_ticks() -> None:
    verdict = compare(
        transcript(OPEN, ("alice", block(1)), tick(1), tick(2), CLOSE),
        transcript(OPEN, tick(1), ("alice", block(1)), tick(2), CLOSE),
        [],
    )

    assert verdict.divergences == (
        divergence(
            "field",
            packet="minecraft:block_update",
            path=TICK_PATH,
            reference=1,
            candidate=2,
            test_case="block_update",
        ),
    ), verdict


def test_a_packet_late_and_different_shows_the_ticks_then_the_difference() -> None:
    verdict = compare(
        transcript(OPEN, ("alice", block(1)), tick(1), tick(2), CLOSE),
        transcript(OPEN, tick(1), ("alice", block(2)), tick(2), CLOSE),
        [],
    )

    assert [(d.kind, d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        ("field", TICK_PATH, 1, 2),
        ("field", None, "01", "02"),
    ], verdict


def test_a_packet_after_the_last_step_is_on_the_tick_after_it() -> None:
    verdict = compare(
        transcript(OPEN, tick(1), ("alice", block(1)), CLOSE),
        transcript(OPEN, ("alice", block(1)), tick(1), CLOSE),
        [],
    )

    assert [(d.reference, d.candidate) for d in verdict.divergences] == [(2, 1)], verdict


def test_an_extra_packet_aligns_as_without_ticks_then_shows_the_ticks() -> None:
    # Packets align on what they are, not on their tick (review of #223): the first of the
    # reference's two matches the candidate's one, a tick apart, and the second is missing.
    verdict = compare(
        transcript(OPEN, ("alice", block(1)), tick(1), ("alice", block(1)), tick(2), CLOSE),
        transcript(OPEN, tick(1), ("alice", block(1)), tick(2), CLOSE),
        [],
    )

    assert [(d.kind, d.index, d.path) for d in verdict.divergences] == [
        ("field", 0, TICK_PATH),
        ("missing", 1, None),
    ], verdict


@pytest.mark.parametrize("count", [1, 3])
def test_packets_all_one_tick_late_show_only_their_ticks(count: int) -> None:
    # Review of #223, MEDIUM: a run of one packet type, each one tick late, must not be
    # paired by tick (missing, a field difference, unexpected) but by order.
    def play(lag: int) -> Transcript:
        items: list[tuple[str, Packet] | str] = [OPEN]
        for k in range(1, count + 2):
            if 1 <= k - lag <= count:
                items.append(("alice", block(k - lag)))
            items.append(tick(k))
        return transcript(*items, CLOSE)

    verdict = compare(play(0), play(1), [])

    assert [(d.index, d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        (index, TICK_PATH, index + 1, index + 2) for index in range(count)
    ], verdict


def test_a_bots_own_tick_mark_ends_its_tick_whatever_the_unnamed_one() -> None:
    # #117's rule, for ticks: alice's tick ends at her own barrier, after the unnamed Mark.
    verdict = compare(
        transcript(OPEN, tick(1), ("alice", block(1)), tick(1, "alice"), CLOSE),
        transcript(OPEN, ("alice", block(1)), tick(1, "alice"), tick(1), CLOSE),
        [],
    )

    assert verdict.outcome is Outcome.MATCH, verdict


def test_a_bot_with_no_tick_mark_of_its_own_ends_its_tick_at_the_unnamed_one() -> None:
    verdict = compare(
        transcript(OPEN, tick(1, "alice"), ("bob", block(1)), tick(1), CLOSE),
        transcript(OPEN, tick(1, "alice"), tick(1), ("bob", block(1)), CLOSE),
        [],
    )

    assert [(d.bot, d.reference, d.candidate) for d in verdict.divergences] == [("bob", 1, 2)], (
        verdict
    )


def test_ticks_count_on_across_windows() -> None:
    def play(late: bool) -> Transcript:  # noqa: FBT001 - a test's own switch
        first = [("alice", block(1)), tick(1)] if not late else [tick(1), ("alice", block(1))]
        return transcript(OPEN, *first, CLOSE, OPEN, tick(2), CLOSE)

    verdict = compare(play(late=False), play(late=True), [])

    assert [(d.reference, d.candidate) for d in verdict.divergences] == [(1, 2)], verdict


def test_a_packet_stamped_at_a_ticks_end_is_on_the_next_tick() -> None:
    # A Mark is stamped a nanosecond after the barrier's answer: what arrives at its time
    # is after it.
    def play(at: int) -> Transcript:
        result = transcript(OPEN, tick(1), CLOSE)
        end = next(mark.t_ns for mark in result.marks if mark.label == tick(1))
        result.record("alice", block(1), t_ns=end + at)
        return result

    verdict = compare(play(0), play(-1), [])

    assert [(d.reference, d.candidate) for d in verdict.divergences] == [(2, 1)], verdict


def test_repeated_packets_late_on_both_sides_pair_in_order() -> None:
    verdict = compare(
        transcript(OPEN, ("alice", block(1)), ("alice", block(2)), tick(1), tick(2), CLOSE),
        transcript(OPEN, tick(1), ("alice", block(1)), ("alice", block(2)), tick(2), CLOSE),
        [],
    )

    assert [(d.index, d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        (0, TICK_PATH, 1, 2),
        (1, TICK_PATH, 1, 2),
    ], verdict


def test_a_side_with_no_tick_marks_compares_without_ticks() -> None:
    # A Transcript with no tick Marks has no ticks (the Group failed before its first step):
    # its packets are never "late".
    stepped = transcript(OPEN, tick(1), ("alice", block(1)), CLOSE)
    unstepped = transcript(OPEN, ("alice", block(1)), CLOSE)

    for reference, candidate in ((stepped, unstepped), (unstepped, stepped)):
        verdict = compare(reference, candidate, [])
        assert verdict.outcome is Outcome.MATCH, verdict


def test_the_tick_path_is_one_no_field_of_a_packet_can_have() -> None:
    # Review of #223, LOW 4: a top-level field called `tick` must not read as the tick.
    def play(value: int) -> Transcript:
        late = packet("minecraft:block_update", b"", fields={"tick": value})
        return transcript(OPEN, ("alice", late), tick(1), CLOSE)

    (field,) = compare(play(1), play(2), []).divergences

    assert field.path == "tick", field
    assert field.path != TICK_PATH


def test_only_play_packets_have_a_tick() -> None:
    # A Bot that joins between steps: its login is compared whole, whatever the tick.
    login = packet("minecraft:hello", b"\x01", state=State.LOGIN)
    verdict = compare(
        transcript(OPEN, ("bob", login), tick(1), CLOSE),
        transcript(OPEN, tick(1), ("bob", login), CLOSE),
        [],
    )

    assert verdict.outcome is Outcome.MATCH, verdict
