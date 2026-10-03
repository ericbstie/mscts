"""GroupContext.observe: an Observation window's Marks, its barrier and its drain."""

import asyncio
import time
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from mscts.bot import Bot
from mscts.codec.packets import Codec, Direction, Packet
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, Outcome, compare
from mscts.group import Group, GroupContext
from mscts.net import Endpoint, ProtocolError
from mscts.run import GroupError, judge, run_group
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.group.test_control import text
from tests.net.fakes import (
    NO_STATISTICS,
    TICK_S,
    Handler,
    JoinScript,
    Peer,
    answer_at_once,
    answer_each_tick,
    join_server,
    never_answer,
    play_server,
    serve,
    status_server,
)

CODEC = Codec.for_target(TARGET)
REQUEST, ANSWER = "minecraft:client_command", "minecraft:award_stats"
BLOCK_UPDATE = "minecraft:block_update"
SYSTEM_CHAT = "minecraft:system_chat"
BLOCK = bytes.fromhex("0000004000001fc4")
"""A block position: `block_update` decodes strictly, so a stand-in needs a position and a state."""
_UNUSED = Endpoint(host="127.0.0.1", port=1)
ALICE_CLOSE = f"{OBSERVE_CLOSE} alice"
"""The close Mark of alice's window."""


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


def window(transcript: Transcript, bot: str = "alice") -> tuple[int, int]:
    """The open and close times of the Transcript's only window, as `bot` sees it."""
    (opened,) = [m for m in transcript.marks if m.label.split()[0] == OBSERVE_OPEN]
    (closed,) = [m for m in transcript.marks if m.label == f"{OBSERVE_CLOSE} {bot}"]
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
    assert labels(transcript) == [OBSERVE_OPEN, ALICE_CLOSE, OBSERVE_CLOSE]


@pytest.mark.asyncio
async def test_a_narrowed_window_names_its_packets_in_its_open_mark() -> None:
    transcript = Transcript(group_id="test/observe", server="fake")
    async with playing(play_server([]), transcript) as context:
        await joined(context)
        async with context.observe(BLOCK_UPDATE, "minecraft:system_chat"):
            pass

    assert labels(transcript) == [
        f"{OBSERVE_OPEN} {BLOCK_UPDATE} minecraft:system_chat",
        ALICE_CLOSE,
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
        ALICE_CLOSE,
        OBSERVE_CLOSE,
        OBSERVE_OPEN,
        OBSERVE_OPEN,
        ALICE_CLOSE,
        OBSERVE_CLOSE,
    ]


@pytest.mark.asyncio
async def test_a_body_that_raises_gets_no_closing_barrier_and_no_close_mark() -> None:
    transcript = Transcript(group_id="test/observe", server="fake")
    seen: list[Packet] = []
    async with playing(play_server(seen), transcript) as context:
        await joined(context)
        with pytest.raises(LookupError):
            async with context.observe():
                raise LookupError

    assert labels(transcript) == [OBSERVE_OPEN]
    requests = [packet.name for packet in seen].count(REQUEST)
    assert requests == 2, "the barrier before the window opens, none at its end"


@pytest.mark.asyncio
async def test_every_bot_in_play_passes_the_barrier_before_the_window_closes() -> None:
    transcript = Transcript(group_id="test/observe", server="fake")
    async with playing(play_server([]), transcript) as context:
        await joined(context, "alice")
        await joined(context, "bob")
        async with context.observe():
            pass

    for bot in ("alice", "bob"):
        _, closed = window(transcript, bot)
        answers = [
            event.t_ns
            for event in transcript.events
            if event.bot == bot and event.packet.name == ANSWER
        ]
        assert len(answers) == 4, bot  # a barrier before the window opens, and one at its end
        assert answers[-1] <= closed, bot


@pytest.mark.asyncio
async def test_each_bots_window_ends_at_its_own_barriers_last_answer() -> None:
    # Audit 2026-10-02, MD2: one close Mark for every Bot, stamped once the slowest barrier
    # had returned, let a Bot whose barrier ended early take what arrived meanwhile.
    transcript = Transcript(group_id="test/observe", server="fake")
    second_requests = 0

    async def one_bot_slow(peer: Peer, request: int) -> None:
        nonlocal second_requests
        if request != 4:  # the closing barrier's second request
            await answer_at_once(peer, request)
            return
        second_requests += 1
        if second_requests == 1:  # the first Bot to ask for it: done, then a straggler
            await answer_at_once(peer, request)
            await asyncio.sleep(0.03)
            await peer.write(peer.raw_frame(BLOCK_UPDATE, BLOCK + b"\x01"))
        else:  # the other: its barrier runs on past the straggler
            await asyncio.sleep(0.15)
            await answer_at_once(peer, request)

    async with playing(play_server([], one_bot_slow), transcript) as context:
        await joined(context, "alice")
        await joined(context, "bob")
        async with context.observe():
            pass

    (straggler,) = [e for e in transcript.events if e.packet.name == BLOCK_UPDATE]
    (closed,) = [m for m in transcript.marks if m.label == f"{OBSERVE_CLOSE} {straggler.bot}"]
    last_answer = max(
        e.t_ns for e in transcript.events if e.bot == straggler.bot and e.packet.name == ANSWER
    )
    assert closed.t_ns == last_answer + 1
    assert closed.t_ns < straggler.t_ns
    assert "block_update.block_state" not in compare(transcript, transcript, []).test_cases


@pytest.mark.asyncio
async def test_what_the_server_sends_before_the_barriers_answer_is_in_the_window() -> None:
    transcript = Transcript(group_id="test/observe", server="fake")

    async def late(peer: Peer, request: int) -> None:
        if request == 4:  # the second request of the barrier at the window's end
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
    assert len(blocks) == 4  # a straggler after each answer, of both barriers
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

    assert labels(transcript) == [OBSERVE_OPEN, ALICE_CLOSE, OBSERVE_CLOSE]
    assert seen == []


@pytest.mark.asyncio
async def test_a_bot_the_group_closed_in_the_window_is_neither_synced_nor_drained_at_its_end() -> (
    None
):
    transcript = Transcript(group_id="test/observe", server="fake")
    seen: list[Packet] = []
    async with playing(play_server(seen), transcript) as context:
        bot = await joined(context)
        async with context.observe():
            await bot.close()

    assert labels(transcript) == [OBSERVE_OPEN, ALICE_CLOSE, OBSERVE_CLOSE]
    requests = [packet.name for packet in seen].count(REQUEST)
    assert requests == 2, "the barrier before the window opened, while the Bot was in play"


LATE_S = 0.02
"""How long after `setup` the fake sends what setup changed to the other Bots."""


def late_setup_server() -> Handler:
    """Join like vanilla, answer the barrier a tick apart, and answer `setup` like Control.

    The Bot that runs the command `setup` gets its feedback at once; every other Bot gets
    the `block_update` it caused `LATE_S` later, still on its way when the feedback lands.
    """
    peers: list[Peer] = []
    late: set[asyncio.Task[int]] = set()

    async def then(peer: Peer) -> None:
        peers.append(peer)
        requests = 0
        async for packet in peer.packets():
            if packet.name == REQUEST:
                requests += 1
                await answer_each_tick(peer, requests)
            elif (packet.fields or {}).get("command") == "setup":
                await peer.write(peer.frame(SYSTEM_CHAT, content=text("done"), overlay=False))
                for other in peers:
                    if other is not peer:
                        update = other.raw_frame(BLOCK_UPDATE, BLOCK + b"\x01")
                        late.add(asyncio.create_task(write_later(other, update)))
        await asyncio.gather(*late)

    return join_server([], JoinScript(then=then))


async def write_later(peer: Peer, frame: bytes) -> int:
    await asyncio.sleep(LATE_S)
    return await peer.write(frame)


@pytest.mark.asyncio
async def test_what_setup_caused_arrives_before_the_window_opens_at_every_bot() -> None:
    # #141: setup passes the barrier on Control only, so a packet setup caused that was
    # still on its way to another Bot could land inside the window on one Instance only.
    # Setup waits for its feedback, as `Control.run` does: the barrier covers no more.
    transcript = Transcript(group_id="test/observe", server="fake")
    async with playing(late_setup_server(), transcript) as context:
        await joined(context, "alice")
        bob = await joined(context, "bob")
        await bob.command("setup")
        await bob.expect(SYSTEM_CHAT, timeout_s=2.0)
        async with context.observe():
            pass

    opened = next(m.t_ns for m in transcript.marks if m.label.split()[0] == OBSERVE_OPEN)
    (update,) = arrivals(transcript, BLOCK_UPDATE)
    assert update < opened
    assert "block_update.block_state" not in compare(transcript, transcript, []).test_cases


@pytest.mark.asyncio
async def test_a_bot_that_took_its_kick_before_a_window_passes_no_barrier_at_its_open() -> None:
    # Review of #181, P3: the barrier before the open skips such a Bot, as the closing one
    # does, so a Group that kicks a Bot during setup does not fail at the next window.
    transcript = Transcript(group_id="test/observe", server="fake")
    async with playing(kicking_server(), transcript) as context:
        alice = await joined(context, "alice")
        await joined(context, "bob")
        await alice.command("kick")
        await alice.expect("minecraft:disconnect", timeout_s=2.0)
        async with context.observe():
            pass

    answers = Counter(e.bot for e in transcript.events if e.packet.name == ANSWER)
    assert answers == {"bob": 4}, answers  # bob passed the opening and the closing barrier


@pytest.mark.asyncio
async def test_a_bot_that_passes_no_barrier_closes_with_the_unnamed_mark_after_every_barrier() -> (
    None
):
    # Review of #179, K6: nothing pinned where such a Bot's close Mark lands.
    transcript = Transcript(group_id="test/observe", server="fake")
    async with playing(play_server([]), transcript) as context:
        await joined(context, "alice")
        bob = await joined(context, "bob")
        async with context.observe():
            await bob.close()

    closes = {m.label: m.t_ns for m in transcript.marks if m.label.startswith(OBSERVE_CLOSE)}
    alices_last_answer = max(
        e.t_ns for e in transcript.events if e.bot == "alice" and e.packet.name == ANSWER
    )
    assert closes[f"{OBSERVE_CLOSE} bob"] == closes[OBSERVE_CLOSE] > alices_last_answer


def kicking_server() -> Handler:
    """Join like vanilla, answer the barrier at once, and disconnect a Bot that runs `kick`."""

    async def then(peer: Peer) -> None:
        requests = 0
        async for packet in peer.packets():
            if packet.name == REQUEST:
                requests += 1
                await answer_at_once(peer, requests)
            elif (packet.fields or {}).get("command") == "kick":
                await peer.write(peer.raw_frame("minecraft:disconnect", KICKED))
                await peer.close()
                return

    return join_server([], JoinScript(then=then))


KICKED = bytes.fromhex("08 0004") + b"kick"
"""A disconnect's reason: an NBT String text component."""


@pytest.mark.asyncio
async def test_a_bot_the_server_disconnected_does_not_fail_the_windows_end() -> None:
    # Audit 2026-10-02, L2: a kicked Bot is still in play by its send State, so the barrier
    # and the drain raised ConnectionClosedError for a Group that tests a kick.
    transcript = Transcript(group_id="test/observe", server="fake")
    async with playing(kicking_server(), transcript) as context:
        alice = await joined(context, "alice")
        await joined(context, "bob")
        async with context.observe():
            await alice.command("kick")
            await alice.expect("minecraft:disconnect", timeout_s=2.0)

    assert sorted(labels(transcript)[1:]) == [
        OBSERVE_CLOSE,
        f"{OBSERVE_CLOSE} alice",
        f"{OBSERVE_CLOSE} bob",
    ]
    bobs_answers = [e for e in transcript.events if e.bot == "bob" and e.packet.name == ANSWER]
    assert len(bobs_answers) == 4  # bob passed both his barriers as usual


@pytest.mark.asyncio
async def test_a_disconnect_the_group_did_not_take_fails_the_bots_barrier() -> None:
    transcript = Transcript(group_id="test/observe", server="fake")

    async def kick_untaken(context: GroupContext) -> None:
        alice = await joined(context, "alice")
        async with context.observe():
            await alice.command("kick")
            await asyncio.sleep(0.1)  # the disconnect and the end arrive, untaken

    async with playing(kicking_server(), transcript) as context:
        with pytest.raises(ProtocolError, match="disconnected alice"):
            await kick_untaken(context)


async def kick_at_the_barrier(peer: Peer, request: int) -> None:  # noqa: ARG001 - an Answer
    """Disconnect the Bot instead of answering its barrier."""
    await peer.write(peer.raw_frame("minecraft:disconnect", KICKED))
    await peer.close()


@pytest.mark.asyncio
async def test_a_candidate_that_disconnects_a_bot_the_reference_keeps_fails() -> None:
    # The disconnect is still queued, untaken by the Group, so the barrier takes it and
    # fails: only a kick the Group took itself is skipped.
    async with serve(CODEC, play_server([])) as endpoint:
        reference = await run_group(OBSERVING, endpoint, server="vanilla", timeout_s=2.0)
    async with serve(CODEC, play_server([], kick_at_the_barrier)) as endpoint:
        with pytest.raises(GroupError) as caught:
            await run_group(OBSERVING, endpoint, server="candidate", timeout_s=2.0)

    verdict = judge(OBSERVING, reference, caught.value)

    assert verdict.outcome is Outcome.MISMATCH, verdict
    failed = verdict.divergences[0]
    assert (failed.kind, failed.bot) == ("failed", "alice"), verdict
    assert "disconnected alice" in str(failed.candidate), verdict


async def kick_after_the_first_barrier(peer: Peer, request: int) -> None:
    """Answer; after the first closing barrier's second answer, disconnect, and close later.

    Requests 1 and 2 are the barrier before the window opens, 3 and 4 the one at its end.
    """
    if request > 4:
        return
    await answer_at_once(peer, request)
    if request == 4:
        await peer.write(peer.raw_frame("minecraft:disconnect", KICKED))
        await asyncio.sleep(0.3)  # the end comes later
        await peer.close()


async def _two_windows(context: GroupContext) -> None:
    await joined(context)
    async with context.observe():
        pass
    await asyncio.sleep(0.05)
    async with context.observe(BLOCK_UPDATE):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("windows", [1, 2])
async def test_a_candidate_that_kicks_a_bot_just_after_its_barrier_mismatches(windows: int) -> None:
    # Review of #179, HIGH 1: the drain took the disconnect, and the Bot was then skipped as
    # though the Group had taken it, so this Candidate matched.
    group = Group(id="test/observe", run=_join_and_observe if windows == 1 else _two_windows)
    async with serve(CODEC, play_server([])) as endpoint:
        reference = await run_group(group, endpoint, server="vanilla", timeout_s=2.0)
    async with serve(CODEC, play_server([], kick_after_the_first_barrier)) as endpoint:
        with pytest.raises(GroupError) as caught:
            await run_group(group, endpoint, server="candidate", timeout_s=2.0)

    verdict = judge(group, reference, caught.value)

    assert verdict.outcome is Outcome.MISMATCH, verdict
    failed = verdict.divergences[0]
    assert (failed.kind, failed.bot) == ("failed", "alice"), verdict
    assert "disconnected alice" in str(failed.candidate), verdict


async def kick_after_the_last_barrier(peer: Peer, request: int) -> None:
    """Answer; 100 ms after the closing barrier's second answer, disconnect, and close later."""
    if request > 4:
        return
    await answer_at_once(peer, request)
    if request == 4:
        await asyncio.sleep(0.1)  # after the window's drain
        await peer.write(peer.raw_frame("minecraft:disconnect", KICKED))
        await asyncio.sleep(0.3)  # the end comes later
        await peer.close()


async def _observe_then_clean_up(context: GroupContext) -> None:
    await joined(context)
    async with context.observe():
        pass
    await asyncio.sleep(0.2)  # cleanup that does not touch alice


@pytest.mark.asyncio
async def test_a_candidate_that_kicks_a_bot_after_the_last_window_mismatches() -> None:
    # #184: nothing took the disconnect, so it was never compared and failed nobody.
    group = Group(id="test/observe", run=_observe_then_clean_up)
    async with serve(CODEC, play_server([])) as endpoint:
        reference = await run_group(group, endpoint, server="vanilla", timeout_s=2.0)
    async with serve(CODEC, play_server([], kick_after_the_last_barrier)) as endpoint:
        with pytest.raises(GroupError) as caught:
            await run_group(group, endpoint, server="candidate", timeout_s=2.0)

    verdict = judge(group, reference, caught.value)

    assert verdict.outcome is Outcome.MISMATCH, verdict
    failed = verdict.divergences[0]
    assert (failed.kind, failed.bot) == ("failed", "alice"), verdict
    assert "disconnected alice" in str(failed.candidate), verdict


async def _take_a_kick(context: GroupContext) -> None:
    alice = await joined(context)
    await alice.command("kick")
    await alice.expect("minecraft:disconnect", timeout_s=2.0)
    await asyncio.sleep(0.1)  # the end of the stream arrives too


@pytest.mark.asyncio
async def test_a_kick_the_group_took_does_not_fail_its_end() -> None:
    group = Group(id="test/observe", run=_take_a_kick)
    async with serve(CODEC, kicking_server()) as endpoint:
        transcript = await run_group(group, endpoint, server="fake", timeout_s=2.0)

    assert arrivals(transcript, "minecraft:disconnect")


async def straggle_after_the_last_barrier(peer: Peer, request: int) -> None:
    """Answer; 100 ms after the closing barrier's second answer, send a block_update."""
    await answer_at_once(peer, request)
    if request == 4:
        await asyncio.sleep(0.1)  # after the window's drain
        await peer.write(peer.raw_frame(BLOCK_UPDATE, BLOCK + b"\x01"))


async def _observe_then_leave(context: GroupContext) -> None:
    alice = await joined(context)
    async with context.observe():
        pass
    await asyncio.sleep(0.2)  # the kick arrives
    await alice.close()


@pytest.mark.asyncio
async def test_a_bot_the_group_closed_is_not_refused_at_its_end() -> None:
    # As at a window's end: a Bot the Group closed itself is given up, and takes nothing.
    group = Group(id="test/observe", run=_observe_then_leave)
    async with serve(CODEC, play_server([], kick_after_the_last_barrier)) as endpoint:
        transcript = await run_group(group, endpoint, server="fake", timeout_s=2.0)

    assert arrivals(transcript, "minecraft:disconnect") == []


@pytest.mark.asyncio
async def test_a_disconnect_that_reached_the_socket_unread_is_refused() -> None:
    # The Group ends as soon as the kick is written, before alice's reader has run: the
    # end catches up with the socket first.
    kicked = asyncio.Event()

    async def kick_then_tell(peer: Peer, request: int) -> None:
        await answer_at_once(peer, request)
        if request == 4:
            await asyncio.sleep(0.1)
            await peer.write(peer.raw_frame("minecraft:disconnect", KICKED))
            kicked.set()

    async def observe_until_kicked(context: GroupContext) -> None:
        await joined(context)
        async with context.observe():
            pass
        await kicked.wait()

    group = Group(id="test/observe", run=observe_until_kicked)
    async with serve(CODEC, play_server([], kick_then_tell)) as endpoint:
        with pytest.raises(GroupError, match="disconnected alice"):
            await run_group(group, endpoint, server="candidate", timeout_s=2.0)


@pytest.mark.asyncio
async def test_a_groups_end_takes_nothing_when_no_disconnect_is_queued() -> None:
    # What arrives after the last window is timing: a Group with no window compares it all.
    group = Group(id="test/observe", run=_observe_then_clean_up)
    async with serve(CODEC, play_server([], straggle_after_the_last_barrier)) as endpoint:
        transcript = await run_group(group, endpoint, server="fake", timeout_s=2.0)

    assert arrivals(transcript, BLOCK_UPDATE) == []


@pytest.mark.asyncio
async def test_a_disconnect_the_group_took_is_inside_the_window_and_compared() -> None:
    transcript = Transcript(group_id="test/observe", server="fake")
    async with playing(kicking_server(), transcript) as context:
        alice = await joined(context, "alice")
        await joined(context, "bob")
        async with context.observe():
            await alice.command("kick")
            await alice.expect("minecraft:disconnect", timeout_s=2.0)

    (disconnect,) = arrivals(transcript, "minecraft:disconnect")
    opened, closed = window(transcript, "alice")
    assert opened <= disconnect < closed
    test_cases = compare(transcript, transcript, []).test_cases
    assert "play:disconnect.reason" in test_cases, test_cases


@pytest.mark.asyncio
async def test_a_bot_that_joins_after_a_window_is_outside_it() -> None:
    # Review of #179, HIGH 2: a Bot that joined after the window closed had no close Mark,
    # so its window never ended and everything it received after was compared.
    transcript = Transcript(group_id="test/observe", server="fake")
    async with playing(play_server([]), transcript) as context:
        await joined(context, "alice")
        async with context.observe():
            pass
        await joined(context, "carol")

    test_cases = compare(transcript, transcript, []).test_cases
    assert not [case for case in test_cases if "chunk" in case or "position" in case], test_cases


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
