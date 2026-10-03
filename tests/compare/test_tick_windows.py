"""Tick windows: a tick-exact Group compares what each Bot received on each tick."""

from mscts.codec.packets import Packet
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


def test_a_packet_on_a_tick_the_other_side_has_not_is_missing_there() -> None:
    # The packet on tick 2 matches; the one on tick 1 has no partner, late or not.
    verdict = compare(
        transcript(OPEN, ("alice", block(1)), tick(1), ("alice", block(1)), tick(2), CLOSE),
        transcript(OPEN, tick(1), ("alice", block(1)), tick(2), CLOSE),
        [],
    )

    assert [(d.kind, d.index) for d in verdict.divergences] == [("missing", 0)], verdict


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
