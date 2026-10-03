"""Bot.sync (the barrier), Bot.drain, and which Bots are in play."""

import asyncio
import time

import pytest

from mscts import bot as bot_module
from mscts.bot import Bot
from mscts.codec.packets import Codec, Direction
from mscts.codec.schemas.play.stats import REQUEST_STATS
from mscts.net import Connection, ConnectionClosedError, ProtocolError
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
    scheduled_server,
    serve_in_thread,
    status_server,
    ticking_server,
    with_bot,
)

CODEC = Codec.for_target(TARGET)
REQUEST, ANSWER = "minecraft:client_command", "minecraft:award_stats"
CLIENTBOUND, SERVERBOUND = Direction.CLIENTBOUND, Direction.SERVERBOUND
WIDE_GAP_S = 0.1
"""A `TICK_GAP_S` far above a localhost round trip, so back-to-back answers are one pass."""
BLOCK = bytes.fromhex("0000004000001fc401")
"""A `block_update` payload: it decodes strictly, so a stand-in one is a position and a state."""
STALL_S = 0.012
"""How long a test blocks the Bot's loop: a GC pause or a chunk burst decoded (audit H1)."""


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


def test_sync_is_one_pair_its_second_request_sent_a_tick_gap_after_the_first_answer(
    wide_gap: float,
) -> None:
    transcript = Transcript(group_id="test/sync", server="fake")
    seen = []

    async def use(bot: Bot) -> None:
        await bot.join()
        await bot.sync()

    # Even a server that answers at once gets one pair: the wait is the proof.
    with_bot(CODEC, transcript, play_server(seen, answer_at_once), use, timeout_s=5.0)

    barrier = barrier_times(transcript)
    assert [name for name, _ in barrier] == [REQUEST, ANSWER] * 2
    _, answered, asked, _ = [t_ns for _, t_ns in barrier]
    assert asked - answered >= round(wide_gap * 1e9)
    assert len([p for p in seen if p.name == REQUEST]) == 2


def test_a_sync_whose_answers_come_a_tick_apart_ends_after_one_pair(wide_gap: float) -> None:
    transcript = Transcript(group_id="test/sync", server="fake")

    async def use(bot: Bot) -> None:
        await bot.join()
        await bot.sync()

    answer = answer_like_vanilla_after(0, tick_s=3 * wide_gap)
    with_bot(CODEC, transcript, play_server([], answer), use, timeout_s=5.0)

    assert [name for name, _ in barrier_times(transcript)] == [REQUEST, ANSWER] * 2
    assert transcript.marks == []


def test_the_second_request_is_sent_no_sooner_than_5_ms_after_the_first_answer_arrived() -> None:
    # Audit 2026-10-02 B2: the real TICK_GAP_S, not `wide_gap`. Answers from one vanilla
    # pass came up to 3.6 ms apart, so a halved wait would let the pair share a pass.
    transcript = Transcript(group_id="test/sync", server="fake")

    async def use(bot: Bot) -> None:
        await bot.join()
        await bot.sync()

    with_bot(CODEC, transcript, play_server([], answer_at_once), use)

    _, answered, asked, _ = [t_ns for _, t_ns in barrier_times(transcript)]
    assert asked - answered >= 5_000_000


def test_the_fakes_tick_is_longer_than_the_tick_gap() -> None:
    assert bot_module.TICK_GAP_S < TICK_S  # a vanilla-like tick is seen as one


def test_a_bot_whose_loop_stalls_after_a_pairs_second_request_does_not_take_one_pass_for_a_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Audit 2026-10-02 H1. The fake runs in its own thread, so it keeps time while the
    # Bot's loop is blocked; a pair sent back to back lands in one 3 ms pass, and the
    # stall stamps the second answer late, as if a tick had passed.
    transcript = Transcript(group_id="test/sync", server="fake")
    real_send = Connection.send
    requests = 0

    async def stalling_send(self: Connection, name: str, /, **fields: object) -> None:
        nonlocal requests
        await real_send(self, name, **fields)
        if name == REQUEST:
            requests += 1
            if requests % 2 == 0:
                # The loop is busy: another Bot decoding, GC, the OS. Blocking it is the
                # point.
                time.sleep(STALL_S)  # noqa: ASYNC251

    monkeypatch.setattr(Connection, "send", stalling_send)

    async def client() -> list[str]:
        with serve_in_thread(CODEC, ticking_server([])) as endpoint:
            bot = await Bot.connect(
                endpoint, TARGET, name="alice", transcript=transcript, timeout_s=5.0
            )
            try:
                await bot.join()
                await bot.sync()
                return received(transcript)
            finally:
                await bot.close()

    assert "minecraft:block_update" in asyncio.run(client())


def test_a_request_answered_at_a_later_pass_still_waits_tick_gap_from_its_answer() -> None:
    # Review A of #163: on a fixed schedule the first request waits for the next pass. A
    # wait counted from when it was sent is over by then, so the second request would
    # land in that same pass, before the tick's block_update.
    transcript = Transcript(group_id="test/sync", server="fake")

    async def use(bot: Bot) -> list[str]:
        await bot.join()
        await bot.sync()
        return received(transcript)

    names, _ = with_bot(CODEC, transcript, scheduled_server([]), use, timeout_s=5.0)
    assert "minecraft:block_update" in names


def test_an_award_stats_that_arrived_before_the_request_is_not_its_answer() -> None:
    # Audit 2026-10-02 H5: a Candidate that answers twice, or a plugin, sends one unasked.
    # It arrives with the join's last chunk batch, before the barrier's first request.
    transcript = Transcript(group_id="test/sync", server="fake")

    async def use(bot: Bot) -> list[str]:
        await bot.join()
        await bot.sync()
        return received(transcript)

    names, _ = with_bot(CODEC, transcript, ticking_server([], stray=True), use, timeout_s=5.0)
    assert "minecraft:block_update" in names


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
