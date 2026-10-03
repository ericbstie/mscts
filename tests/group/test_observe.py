"""GroupContext.observe: an Observation window's Marks, its barrier and its drain."""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from mscts.bot import Bot
from mscts.codec.packets import Codec, Direction, Packet
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, Outcome, compare
from mscts.group import Group, GroupContext
from mscts.net import Endpoint
from mscts.run import GroupError, judge, run_group
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import (
    NO_STATISTICS,
    TICK_S,
    Handler,
    Peer,
    answer_at_once,
    never_answer,
    play_server,
    serve,
    status_server,
)

CODEC = Codec.for_target(TARGET)
REQUEST, ANSWER = "minecraft:client_command", "minecraft:award_stats"
BLOCK_UPDATE = "minecraft:block_update"
BLOCK = bytes.fromhex("0000004000001fc4")
"""A block position: `block_update` decodes strictly, so a stand-in needs a position and a state."""
_UNUSED = Endpoint(host="127.0.0.1", port=1)


@asynccontextmanager
async def playing(
    handler: Handler, transcript: Transcript, *, timeout_s: float = 2.0
) -> AsyncIterator[GroupContext]:
    """A GroupContext against a fake server running `handler`, closed however the body ends."""
    async with serve(CODEC, handler) as endpoint:
        context = GroupContext(endpoint, transcript, timeout_s=timeout_s)
        try:
            yield context
        finally:
            await context.close()


async def joined(context: GroupContext, name: str = "alice") -> Bot:
    bot = await context.bot(name)
    await bot.join()
    return bot


def labels(transcript: Transcript) -> list[str]:
    return [mark.label for mark in transcript.marks]


def window(transcript: Transcript) -> tuple[int, int]:
    """The open and close times of the Transcript's only window."""
    opened, closed = transcript.marks
    assert (opened.label.split()[0], closed.label) == (OBSERVE_OPEN, OBSERVE_CLOSE)
    return opened.t_ns, closed.t_ns


def arrivals(transcript: Transcript, name: str) -> list[int]:
    return [
        event.t_ns
        for event in transcript.events
        if event.packet.name == name and event.packet.direction is Direction.CLIENTBOUND
    ]


@pytest.mark.asyncio
async def test_a_window_marks_where_it_opens_and_where_it_closes() -> None:
    transcript = Transcript(group_id="test/observe", server="fake")
    async with playing(play_server([]), transcript) as context:
        await joined(context)
        async with context.observe():
            inside = labels(transcript)

    assert inside == [OBSERVE_OPEN]
    assert labels(transcript) == [OBSERVE_OPEN, OBSERVE_CLOSE]


@pytest.mark.asyncio
async def test_a_narrowed_window_names_its_packets_in_its_open_mark() -> None:
    transcript = Transcript(group_id="test/observe", server="fake")
    async with playing(play_server([]), transcript) as context:
        await joined(context)
        async with context.observe(BLOCK_UPDATE, "minecraft:system_chat"):
            pass

    assert labels(transcript) == [
        f"{OBSERVE_OPEN} {BLOCK_UPDATE} minecraft:system_chat",
        OBSERVE_CLOSE,
    ]


NOT_A_PLAY_PACKET = [
    # Audit 2026-10-02, MD1: each was accepted, and a window narrowed to it compared nothing.
    "minecraft:block_updat",
    "block_update",
    "",
    "minecraft:block update",
    "minecraft:a\tb",
    "minecraft:client_command",  # serverbound
    "minecraft:login_finished",  # not in play
]
HEARTBEATS = ["minecraft:set_time", "minecraft:keep_alive", "minecraft:award_stats"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", NOT_A_PLAY_PACKET)
async def test_observe_refuses_a_name_that_is_not_a_clientbound_play_packet(name: str) -> None:
    transcript = Transcript(group_id="test/observe", server="fake")
    context = GroupContext(_UNUSED, transcript, timeout_s=1.0)

    with pytest.raises(ValueError, match="not a packet the server sends in play"):
        async with context.observe(BLOCK_UPDATE, name):
            pass
    with pytest.raises(ValueError, match="not a packet the server sends in play"):
        async with context.observe(BLOCK_UPDATE, until=name):
            pass
    assert transcript.marks == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name", HEARTBEATS)
async def test_observe_refuses_a_heartbeat_packet(name: str) -> None:
    transcript = Transcript(group_id="test/observe", server="fake")
    context = GroupContext(_UNUSED, transcript, timeout_s=1.0)

    with pytest.raises(ValueError, match="a heartbeat packet"):
        async with context.observe(name):
            pass
    with pytest.raises(ValueError, match="a heartbeat packet"):
        async with context.observe(until=name):
            pass
    assert transcript.marks == []


@pytest.mark.asyncio
async def test_windows_do_not_nest_and_one_may_follow_another() -> None:
    transcript = Transcript(group_id="test/observe", server="fake")
    async with playing(play_server([]), transcript) as context:
        await joined(context)
        async with context.observe():
            with pytest.raises(ValueError, match="windows do not nest"):
                async with context.observe():
                    pass
        with pytest.raises(LookupError):
            async with context.observe():
                raise LookupError
        async with context.observe():
            pass

    assert labels(transcript) == [
        OBSERVE_OPEN,
        OBSERVE_CLOSE,
        OBSERVE_OPEN,
        OBSERVE_OPEN,
        OBSERVE_CLOSE,
    ]


@pytest.mark.asyncio
async def test_a_body_that_raises_gets_no_barrier_and_no_close_mark() -> None:
    transcript = Transcript(group_id="test/observe", server="fake")
    seen: list[Packet] = []
    async with playing(play_server(seen), transcript) as context:
        await joined(context)
        with pytest.raises(LookupError):
            async with context.observe():
                raise LookupError

    assert labels(transcript) == [OBSERVE_OPEN]
    assert REQUEST not in [packet.name for packet in seen]


@pytest.mark.asyncio
async def test_every_bot_in_play_passes_the_barrier_before_the_window_closes() -> None:
    transcript = Transcript(group_id="test/observe", server="fake")
    async with playing(play_server([]), transcript) as context:
        await joined(context, "alice")
        await joined(context, "bob")
        async with context.observe():
            pass

    _, closed = window(transcript)
    for bot in ("alice", "bob"):
        answers = [
            event.t_ns
            for event in transcript.events
            if event.bot == bot and event.packet.name == ANSWER
        ]
        assert len(answers) == 2, bot
        assert answers[-1] <= closed, bot


@pytest.mark.asyncio
async def test_what_the_server_sends_before_the_barriers_answer_is_in_the_window() -> None:
    transcript = Transcript(group_id="test/observe", server="fake")

    async def late(peer: Peer, request: int) -> None:
        if request == 2:
            await asyncio.sleep(0.2)
            await peer.write(peer.raw_frame(BLOCK_UPDATE, BLOCK + b"\x01"))
        await answer_at_once(peer, request)

    async with playing(play_server([], late), transcript) as context:
        await joined(context)
        async with context.observe():
            pass

    opened, closed = window(transcript)
    (block,) = arrivals(transcript, BLOCK_UPDATE)
    assert opened <= block <= closed
    test_cases = compare(transcript, transcript, []).test_cases
    assert "block_update.block_state" in test_cases
    assert not {"award_stats", "chunk_batch_finished"} & set(test_cases), test_cases


@pytest.mark.asyncio
async def test_the_drain_takes_what_arrived_after_the_barrier_without_waiting() -> None:
    transcript = Transcript(group_id="test/observe", server="fake")

    async def with_a_straggler(peer: Peer, request: int) -> None:
        if request % 2 == 0:
            await asyncio.sleep(TICK_S)  # a barrier's second answer comes a tick later
        answer = peer.raw_frame(ANSWER, NO_STATISTICS)
        straggler = peer.raw_frame(BLOCK_UPDATE, BLOCK + bytes([request]))
        await peer.write(answer + straggler)

    async with playing(play_server([], with_a_straggler), transcript, timeout_s=5.0) as context:
        await joined(context)
        async with context.observe():
            started = time.monotonic()
        took = time.monotonic() - started

    _, closed = window(transcript)
    blocks = arrivals(transcript, BLOCK_UPDATE)
    assert len(blocks) == 2
    assert blocks[-1] <= closed
    assert took < 1.0, f"closing the window took {took:.2f} s"


@pytest.mark.asyncio
async def test_a_bot_not_in_play_is_not_synced() -> None:
    transcript = Transcript(group_id="test/observe", server="fake")
    seen: list[Packet] = []
    async with playing(status_server("{}", seen), transcript) as context:
        await context.bot("alice")
        async with context.observe():
            pass

    assert labels(transcript) == [OBSERVE_OPEN, OBSERVE_CLOSE]
    assert seen == []


@pytest.mark.asyncio
async def test_a_bot_the_group_closed_is_neither_synced_nor_drained() -> None:
    transcript = Transcript(group_id="test/observe", server="fake")
    seen: list[Packet] = []
    async with playing(play_server(seen), transcript) as context:
        bot = await joined(context)
        async with context.observe():
            await bot.close()

    assert labels(transcript) == [OBSERVE_OPEN, OBSERVE_CLOSE]
    assert REQUEST not in [packet.name for packet in seen]


async def _join_and_observe(context: GroupContext) -> None:
    await joined(context)
    async with context.observe():
        pass


OBSERVING = Group(id="test/observe", run=_join_and_observe)


@pytest.mark.asyncio
async def test_a_candidate_that_never_answers_the_barrier_fails_rather_than_errs() -> None:
    async with serve(CODEC, play_server([])) as endpoint:
        reference = await run_group(OBSERVING, endpoint, server="vanilla", timeout_s=2.0)
    async with serve(CODEC, play_server([], never_answer)) as endpoint:
        with pytest.raises(GroupError) as caught:
            await run_group(OBSERVING, endpoint, server="candidate", timeout_s=0.5)

    verdict = judge(OBSERVING, reference, caught.value)

    assert verdict.outcome is Outcome.MISMATCH, verdict
    failed = verdict.divergences[0]
    assert (failed.kind, failed.bot) == ("failed", "alice"), verdict
    assert str(failed.candidate).startswith("TimeoutError"), verdict
