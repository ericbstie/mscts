"""Bot.sync (the barrier), Bot.drain, and which Bots are in play."""

import asyncio
import time
from collections.abc import Callable

import pytest

from mscts import bot as bot_module
from mscts.bot import Bot
from mscts.codec.packets import Codec, Direction, Packet
from mscts.codec.schemas.play.stats import REQUEST_STATS
from mscts.net import ConnectionClosedError, ProtocolError
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import (
    NO_STATISTICS,
    TICK_S,
    Peer,
    answer_at_once,
    answer_each_tick,
    answer_like_vanilla_after,
    never_answer,
    play_server,
    status_server,
    with_bot,
)

CODEC = Codec.for_target(TARGET)
REQUEST, ANSWER = "minecraft:client_command", "minecraft:award_stats"
CLIENTBOUND, SERVERBOUND = Direction.CLIENTBOUND, Direction.SERVERBOUND
WIDE_GAP_S = 0.1
"""A `TICK_GAP_S` far above a localhost round trip, so back-to-back answers are one pass."""
BLOCK = bytes.fromhex("0000004000001fc401")
"""A `block_update` payload: it decodes strictly, so a stand-in one is a position and a state."""


def received(transcript: Transcript) -> list[str]:
    return [e.packet.name for e in transcript.events if e.packet.direction is CLIENTBOUND]


@pytest.fixture
def wide_gap(monkeypatch: pytest.MonkeyPatch) -> float:
    """Make a tick gap `WIDE_GAP_S` long: an answer 0.2 ms after the last is the same pass."""
    monkeypatch.setattr(bot_module, "TICK_GAP_S", WIDE_GAP_S)
    return WIDE_GAP_S


def barrier_times(transcript: Transcript) -> list[tuple[str, int]]:
    """Each request the Bot sent and answer it took, as (name, ns), in time order."""
    return [
        (event.packet.name, event.t_ns)
        for event in transcript.events
        if event.packet.name in {REQUEST, ANSWER}
    ]


def test_sync_asks_for_statistics_twice_each_after_the_last_answer() -> None:
    transcript = Transcript(group_id="test/sync", server="fake")
    seen = []

    async def use(bot: Bot) -> None:
        await bot.join()
        await bot.sync()

    with_bot(CODEC, transcript, play_server(seen), use)

    barrier = [
        (event.packet.direction, event.packet.name)
        for event in transcript.events
        if event.packet.name in {REQUEST, ANSWER}
    ]
    assert barrier == [(SERVERBOUND, REQUEST), (CLIENTBOUND, ANSWER)] * 2
    assert [p.fields for p in seen if p.name == REQUEST] == [{"action": REQUEST_STATS}] * 2


def test_two_answers_from_one_pass_make_sync_wait_and_ask_in_a_new_pair(wide_gap: float) -> None:
    transcript = Transcript(group_id="test/sync", server="fake")
    seen = []

    async def use(bot: Bot) -> None:
        await bot.join()
        await bot.sync()

    # The first two requests are answered at once, a fraction of a millisecond apart;
    # from the third, like vanilla: the second of a pair a tick later.
    answer = answer_like_vanilla_after(2, tick_s=3 * wide_gap)
    with_bot(CODEC, transcript, play_server(seen, answer), use, timeout_s=5.0)

    barrier = barrier_times(transcript)
    assert [name for name, _ in barrier] == [REQUEST, ANSWER] * 4
    times = [t_ns for _, t_ns in barrier]
    wait_ns = round(wide_gap * 1e9)
    assert times[3] - times[1] < wait_ns  # the first pair's answers shared a pass
    assert times[4] - times[3] >= wait_ns  # so the Bot waited before asking again
    assert times[2] - times[1] < wait_ns  # the second request of a pair follows at once
    assert times[6] - times[5] < wait_ns
    assert times[7] - times[5] >= wait_ns  # and the new pair's answers were a tick apart
    assert transcript.marks == []
    assert len([p for p in seen if p.name == REQUEST]) == 4


def test_a_sync_whose_answers_come_a_tick_apart_ends_after_one_pair(wide_gap: float) -> None:
    transcript = Transcript(group_id="test/sync", server="fake")

    async def use(bot: Bot) -> None:
        await bot.join()
        await bot.sync()

    answer = answer_like_vanilla_after(0, tick_s=3 * wide_gap)
    with_bot(CODEC, transcript, play_server([], answer), use, timeout_s=5.0)

    assert [name for name, _ in barrier_times(transcript)] == [REQUEST, ANSWER] * 2
    assert transcript.marks == []


def test_a_server_that_never_shows_a_tick_ends_sync_at_the_cap_with_a_mark(
    wide_gap: float,
) -> None:
    transcript = Transcript(group_id="test/sync", server="fake")
    seen = []

    async def use(bot: Bot) -> None:
        await bot.join()
        await bot.sync()  # returns, however the server answers

    with_bot(CODEC, transcript, play_server(seen, answer_at_once), use, timeout_s=5.0)

    barrier = barrier_times(transcript)
    assert [name for name, _ in barrier] == [REQUEST, ANSWER] * bot_module.SYNC_MAX_TRIPS
    assert len([p for p in seen if p.name == REQUEST]) == bot_module.SYNC_MAX_TRIPS
    (mark,) = transcript.marks
    assert mark.label == f"{bot_module.SYNC_CAPPED} alice"
    assert mark.label.split()[0] == "sync:capped"
    assert mark.t_ns >= barrier[-1][1]  # left once the last answer had arrived
    wait_ns = round(wide_gap * 1e9)
    times = [t_ns for _, t_ns in barrier]
    pairs = list(
        zip(times[1::4], times[4::4], strict=False)
    )  # a pair's last answer, the next request
    assert pairs
    assert all(asked - answered >= wait_ns for answered, asked in pairs)


def test_the_gap_is_between_when_answers_arrived_not_when_the_bot_took_them(
    wide_gap: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript = Transcript(group_id="test/sync", server="fake")
    taken = []
    real_expect = Bot.expect

    async def slow_to_take_the_second(
        self: Bot, name: str, *, timeout_s: float, where: Callable[[Packet], bool] | None = None
    ) -> Packet:
        packet = await real_expect(self, name, timeout_s=timeout_s, where=where)
        if name == ANSWER:
            taken.append(packet)
            if len(taken) % 2 == 0:  # a busy Bot looks at the second answer a tick late
                await asyncio.sleep(1.5 * wide_gap)
        return packet

    monkeypatch.setattr(Bot, "expect", slow_to_take_the_second)

    async def use(bot: Bot) -> None:
        await bot.join()
        await bot.sync()

    with_bot(CODEC, transcript, play_server([], answer_at_once), use, timeout_s=5.0)

    assert len(taken) == bot_module.SYNC_MAX_TRIPS  # the answers came together, so it capped
    (mark,) = transcript.marks
    assert mark.label == f"{bot_module.SYNC_CAPPED} alice"


def test_the_cap_is_a_whole_number_of_pairs() -> None:
    assert bot_module.SYNC_MAX_TRIPS % 2 == 0
    assert bot_module.SYNC_MAX_TRIPS >= 4
    assert bot_module.TICK_GAP_S < TICK_S  # a vanilla-like tick is seen as one


def test_sync_takes_everything_the_server_sent_before_its_last_answer() -> None:
    transcript = Transcript(group_id="test/sync", server="fake")

    async def late(peer: Peer, request: int) -> None:
        if request == 2:
            await asyncio.sleep(0.2)
            await peer.write(peer.raw_frame("minecraft:block_update", BLOCK))
        await answer_at_once(peer, request)

    async def use(bot: Bot) -> list[str]:
        await bot.join()
        await bot.sync()
        return received(transcript)

    names, _ = with_bot(CODEC, transcript, play_server([], late), use)
    assert names[-2:] == ["minecraft:block_update", ANSWER]


def test_a_sync_that_gets_no_answer_times_out_as_the_bots_failure() -> None:
    transcript = Transcript(group_id="test/sync", server="fake")

    async def use(bot: Bot) -> bool:
        await bot.join()
        with pytest.raises(TimeoutError) as caught:
            await bot.sync()
        return caught.value is bot.failure

    failed_here, _ = with_bot(CODEC, transcript, play_server([], never_answer), use, timeout_s=0.5)
    assert failed_here


def test_sync_refuses_a_bot_that_is_not_in_play() -> None:
    transcript = Transcript(group_id="test/sync", server="fake")

    async def use(bot: Bot) -> None:
        with pytest.raises(ProtocolError, match="sync needs a Bot in play, not one in handshake"):
            await bot.sync()

    with_bot(CODEC, transcript, status_server("{}", []), use)
    assert transcript.events == []


def test_a_bot_is_in_play_from_its_join_until_it_is_closed() -> None:
    transcript = Transcript(group_id="test/sync", server="fake")

    async def use(bot: Bot) -> list[tuple[bool, bool]]:
        states = [(bot.in_play, bot.closed)]
        await bot.join()
        states.append((bot.in_play, bot.closed))
        await bot.close()
        states.append((bot.in_play, bot.closed))
        return states

    states, _ = with_bot(CODEC, transcript, play_server([]), use)
    assert states == [(False, False), (True, False), (False, True)]


def test_drain_takes_what_has_arrived_and_does_not_wait_for_more() -> None:
    transcript = Transcript(group_id="test/sync", server="fake")

    async def with_stragglers(peer: Peer, request: int) -> None:
        if request % 2 == 0:
            await asyncio.sleep(TICK_S)  # a barrier's second answer comes a tick later
        straggler = peer.raw_frame("minecraft:block_update", BLOCK)
        await peer.write(peer.raw_frame(ANSWER, NO_STATISTICS) + straggler + straggler)

    async def use(bot: Bot) -> tuple[int, int, float]:
        await bot.join()
        await bot.sync()
        before = received(transcript).count("minecraft:block_update")
        started = time.monotonic()
        await bot.drain()
        took = time.monotonic() - started
        return before, received(transcript).count("minecraft:block_update"), took

    (before, after, took), _ = with_bot(
        CODEC, transcript, play_server([], with_stragglers), use, timeout_s=5.0
    )
    assert (before, after) == (2, 4)
    assert took < 1.0, f"drain took {took:.2f} s"


def test_a_drain_that_finds_the_connection_closed_raises_as_the_bots_failure() -> None:
    transcript = Transcript(group_id="test/sync", server="fake")

    async def then_close(peer: Peer, request: int) -> None:
        await answer_each_tick(peer, request)
        if request == 2:
            await peer.close()

    async def use(bot: Bot) -> bool:
        await bot.join()
        await bot.sync()
        await asyncio.sleep(0.2)  # for the close to arrive
        with pytest.raises(ConnectionClosedError) as caught:
            await bot.drain()
        return caught.value is bot.failure

    failed_here, _ = with_bot(CODEC, transcript, play_server([], then_close), use)
    assert failed_here
