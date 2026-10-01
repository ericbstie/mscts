"""Bot.sync (the barrier), Bot.drain, and which Bots are in play."""

import asyncio
import time

import pytest

from mscts.bot import Bot
from mscts.codec.packets import Codec, Direction
from mscts.codec.schemas.play.stats import REQUEST_STATS
from mscts.net import ProtocolError
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import (
    NO_STATISTICS,
    Peer,
    answer_at_once,
    never_answer,
    play_server,
    status_server,
    with_bot,
)

CODEC = Codec.for_target(TARGET)
REQUEST, ANSWER = "minecraft:client_command", "minecraft:award_stats"
CLIENTBOUND, SERVERBOUND = Direction.CLIENTBOUND, Direction.SERVERBOUND


def received(transcript: Transcript) -> list[str]:
    return [e.packet.name for e in transcript.events if e.packet.direction is CLIENTBOUND]


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


def test_sync_takes_everything_the_server_sent_before_its_last_answer() -> None:
    transcript = Transcript(group_id="test/sync", server="fake")

    async def late(peer: Peer, request: int) -> None:
        if request == 2:
            await asyncio.sleep(0.2)
            await peer.write(peer.raw_frame("minecraft:block_update", b"\x01"))
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

    async def with_a_straggler(peer: Peer, request: int) -> None:  # noqa: ARG001 - an Answer
        answer = peer.raw_frame(ANSWER, NO_STATISTICS)
        await peer.write(answer + peer.raw_frame("minecraft:block_update", b"\x01"))

    async def use(bot: Bot) -> tuple[int, int, float]:
        await bot.join()
        await bot.sync()
        before = received(transcript).count("minecraft:block_update")
        started = time.monotonic()
        await bot.drain()
        took = time.monotonic() - started
        return before, received(transcript).count("minecraft:block_update"), took

    (before, after, took), _ = with_bot(
        CODEC, transcript, play_server([], with_a_straggler), use, timeout_s=5.0
    )
    assert (before, after) == (1, 2)
    assert took < 1.0, f"drain took {took:.2f} s"
