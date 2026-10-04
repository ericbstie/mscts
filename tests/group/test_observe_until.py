"""GroupContext.observe(until=...): a window that ends at a packet's arrival, with no barrier."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from mscts.bot import SYNC_REQUESTS, Bot
from mscts.codec.packets import Codec, Direction, Packet, State
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, Outcome, compare
from mscts.group import Group, GroupContext
from mscts.net import Endpoint, ProtocolError
from mscts.run import GroupError, judge, run_group
from mscts.spec import CONTROL_PLAYER
from mscts.target import TARGET
from mscts.transcript import Mark, Transcript
from tests.net.fakes import (
    Handler,
    JoinScript,
    Peer,
    answer_each_tick,
    join_server,
    serve,
)

CODEC = Codec.for_target(TARGET)
REQUEST = "minecraft:client_command"
BLOCK_UPDATE = "minecraft:block_update"
BATCH_FINISHED = "minecraft:chunk_batch_finished"
DIFFICULTY = "minecraft:change_difficulty"
"""A play packet sent both ways that can end a window (a keep-alive is a heartbeat)."""
BLOCK = bytes.fromhex("0000004000001fc4")
"""A block position: `block_update` decodes strictly, so a stand-in needs a position and a state."""
GAP_S = 0.04
"""How long the fake waits between what it sends, so each arrives in a read of its own."""


def server(seen: list[Packet], *, answers: bool = True, later_state: int = 1) -> Handler:
    """Join like vanilla, then answer the command `batch` (if `answers`) with four packets.

    A block_update, a chunk_batch_finished, a later block_update whose state is
    `later_state`, and a second chunk_batch_finished, each `GAP_S` after the one before. A
    statistics request is answered like vanilla's.
    """

    async def then(peer: Peer) -> None:
        requests = 0
        async for packet in peer.packets():
            seen.append(packet)
            if packet.name == REQUEST:
                requests += 1
                await answer_each_tick(peer, requests)
            elif answers and (packet.fields or {}).get("command") == "burst":
                # One write, so one read at the Bot: all three frames arrive together.
                await peer.write(
                    peer.raw_frame(BLOCK_UPDATE, BLOCK + b"\x01")
                    + peer.frame(BATCH_FINISHED, batch_size=1)
                    + peer.raw_frame(BLOCK_UPDATE, BLOCK + bytes([later_state]))
                )
            elif answers and (packet.fields or {}).get("command") == "batch":
                await peer.write(peer.raw_frame(BLOCK_UPDATE, BLOCK + b"\x01"))
                await asyncio.sleep(GAP_S)
                await peer.send(BATCH_FINISHED, batch_size=1)
                await asyncio.sleep(GAP_S)
                await peer.write(peer.raw_frame(BLOCK_UPDATE, BLOCK + bytes([later_state])))
                await asyncio.sleep(GAP_S)
                await peer.send(BATCH_FINISHED, batch_size=2)

    return join_server(seen, JoinScript(then=then))


@asynccontextmanager
async def playing(handler: Handler, transcript: Transcript) -> AsyncIterator[GroupContext]:
    """A GroupContext against a fake server running `handler`, closed however the body ends."""
    async with serve(CODEC, handler) as endpoint:
        context = GroupContext(endpoint, transcript, timeout_s=2.0)
        try:
            yield context
        finally:
            await context.close()


async def play(*, until: str | None, later_state: int = 1) -> Transcript:
    """A Bot joins, then a window sees the server's four packets, and the Bot waits for them."""
    transcript = Transcript(group_id="test/until", server="fake")
    async with playing(server([], later_state=later_state), transcript) as context:
        bot = await context.bot("alice")
        await bot.join()
        async with context.observe(until=until):
            await bot.command("batch")
            await asyncio.sleep(8 * GAP_S)
    return transcript


def arrivals(transcript: Transcript, name: str) -> list[int]:
    return [
        event.t_ns
        for event in transcript.events
        if event.packet.name == name and event.packet.direction is Direction.CLIENTBOUND
    ]


@pytest.mark.asyncio
async def test_the_window_closes_when_the_first_such_packet_arrived_not_when_it_was_taken() -> None:
    transcript = Transcript(group_id="test/until", server="fake")
    seen: list[Packet] = []
    async with playing(server(seen), transcript) as context:
        bot = await context.bot("alice")
        await bot.join()
        async with context.observe(until=BATCH_FINISHED):
            await bot.command("batch")
            await asyncio.sleep(8 * GAP_S)
            exit_ns = transcript.now_ns()

    opened, closed = transcript.marks
    assert (opened.label, closed.label) == (OBSERVE_OPEN, OBSERVE_CLOSE)
    joined, first, _ = arrivals(transcript, BATCH_FINISHED)
    assert joined < opened.t_ns <= first
    assert closed.t_ns == first + 1, "just after the arrival (see the burst test)"
    assert exit_ns - closed.t_ns > 4 * GAP_S * 1e9, "the Mark is the arrival, not the time taken"
    names = [packet.name for packet in seen]
    assert names.count(REQUEST) == SYNC_REQUESTS, (
        "the barrier before the window opens, none at its end"
    )


@pytest.mark.asyncio
async def test_a_later_such_packet_and_what_follows_the_first_are_not_compared() -> None:
    first = await play(until=BATCH_FINISHED, later_state=1)
    second = await play(until=BATCH_FINISHED, later_state=2)

    _, closed = first.marks
    before, after = arrivals(first, BLOCK_UPDATE)
    assert before < closed.t_ns < after
    verdict = compare(first, second, [])
    assert verdict.outcome is Outcome.MATCH, verdict
    assert "block_update.block_state" in verdict.test_cases, "what came before is compared"


async def burst(*, trailing_state: int) -> Transcript:
    """A Bot joins, then a window sees one read with a block_update, the batch, a block_update."""
    transcript = Transcript(group_id="test/until", server="fake")
    async with playing(server([], later_state=trailing_state), transcript) as context:
        bot = await context.bot("alice")
        await bot.join()
        async with context.observe(until=BATCH_FINISHED):
            await bot.command("burst")
            await asyncio.sleep(4 * GAP_S)
    return transcript


@pytest.mark.asyncio
async def test_what_one_read_brought_before_the_packet_is_in_the_window_and_after_it_is_not() -> (
    None
):
    # A join's packets come in a few reads, so a window that closed before the packet's
    # stamp would lose the whole read. Frames of one read are a nanosecond apart, so the
    # close Mark falls between the packet and the frame behind it (#105).
    first = await burst(trailing_state=1)
    second = await burst(trailing_state=2)

    before, after = arrivals(first, BLOCK_UPDATE)
    _, batch = arrivals(first, BATCH_FINISHED)
    _, closed = first.marks
    assert (batch, after) == (before + 1, before + 2), "one read took all three"
    assert closed.t_ns == batch + 1
    verdict = compare(first, second, [])
    assert verdict.outcome is Outcome.MATCH, verdict
    assert "block_update.block_state" in verdict.test_cases, "what came before it is compared"


@pytest.mark.asyncio
async def test_a_window_with_a_barrier_does_compare_what_the_server_sends_after_it_all() -> None:
    verdict = compare(
        await play(until=None, later_state=1), await play(until=None, later_state=2), []
    )

    assert verdict.outcome is Outcome.MISMATCH, verdict


@pytest.mark.asyncio
async def test_a_packet_that_arrived_before_the_window_opened_does_not_close_it() -> None:
    transcript = Transcript(group_id="test/until", server="fake")
    async with playing(server([]), transcript) as context:
        bot = await context.bot("alice")
        await bot.join()
        assert len(arrivals(transcript, BATCH_FINISHED)) == 1
        with pytest.raises(ProtocolError, match=r"minecraft:chunk_batch_finished"):
            async with context.observe(until=BATCH_FINISHED):
                pass

    assert [mark.label for mark in transcript.marks] == [OBSERVE_OPEN]


@pytest.mark.asyncio
async def test_a_packet_of_another_state_does_not_close_it() -> None:
    transcript = Transcript(group_id="test/until", server="fake")
    brand = "minecraft:custom_payload"  # configuration sends it, the fake's play does not

    async def join_inside(context: GroupContext) -> None:
        async with context.observe(until=brand):
            bot = await context.bot("alice")
            await bot.join()

    async with playing(server([]), transcript) as context:
        with pytest.raises(ProtocolError, match=r"minecraft:custom_payload"):
            await join_inside(context)

    assert brand in [event.packet.name for event in transcript.events]


@pytest.mark.asyncio
async def test_only_a_packet_the_server_sent_closes_it() -> None:
    payloads = {Direction.CLIENTBOUND: b"\x00\x01", Direction.SERVERBOUND: b"\x00"}
    transcript = Transcript(group_id="test/until", server="fake")
    context = GroupContext(Endpoint(host="127.0.0.1", port=1), transcript, timeout_s=1.0)

    def heard(direction: Direction) -> Packet:
        packet_id = CODEC.packet_id(State.PLAY, direction, DIFFICULTY)
        return CODEC.decode(State.PLAY, direction, bytes([packet_id]) + payloads[direction])

    async def observe_with_a_sent_one() -> None:
        async with context.observe(until=DIFFICULTY):
            transcript.record("alice", heard(Direction.SERVERBOUND), t_ns=transcript.now_ns())

    with pytest.raises(ProtocolError, match=DIFFICULTY):
        await observe_with_a_sent_one()
    async with context.observe(until=DIFFICULTY):
        transcript.record("alice", heard(Direction.SERVERBOUND), t_ns=transcript.now_ns())
        arrival = transcript.now_ns()
        transcript.record("alice", heard(Direction.CLIENTBOUND), t_ns=arrival)
        transcript.record("bob", heard(Direction.CLIENTBOUND), t_ns=transcript.now_ns())

    assert transcript.marks[-1] == Mark(t_ns=arrival + 1, label=OBSERVE_CLOSE)


def _heard_by(transcript: Transcript, bot: str, name: str, *, at: int) -> None:
    packet_id = CODEC.packet_id(State.PLAY, Direction.CLIENTBOUND, name)
    packet = CODEC.decode(State.PLAY, Direction.CLIENTBOUND, bytes([packet_id, 0, 1]))
    transcript.record(bot, packet, t_ns=at)


@pytest.mark.asyncio
async def test_a_packet_that_control_received_does_not_close_it() -> None:
    # Compare never compares Control's receipts, so what only Control heard is no end.
    transcript = Transcript(group_id="test/until", server="fake")
    context = GroupContext(Endpoint(host="127.0.0.1", port=1), transcript, timeout_s=1.0)

    async with context.observe(until=DIFFICULTY):
        _heard_by(transcript, CONTROL_PLAYER, DIFFICULTY, at=transcript.now_ns())
        arrival = transcript.now_ns()
        _heard_by(transcript, "alice", DIFFICULTY, at=arrival)

    assert transcript.marks[-1] == Mark(t_ns=arrival + 1, label=OBSERVE_CLOSE)
    with pytest.raises(ProtocolError, match=DIFFICULTY):
        async with context.observe(until=DIFFICULTY):
            _heard_by(transcript, CONTROL_PLAYER, DIFFICULTY, at=transcript.now_ns())


@pytest.mark.asyncio
async def test_the_earliest_arrival_at_any_bot_closes_it_whichever_was_recorded_first() -> None:
    # A Bot records a frame when it takes it, so across Bots the order of recording is not
    # the order of arrival.
    transcript = Transcript(group_id="test/until", server="fake")
    context = GroupContext(Endpoint(host="127.0.0.1", port=1), transcript, timeout_s=1.0)

    async with context.observe(until=DIFFICULTY):
        earlier = transcript.now_ns()
        later = transcript.now_ns()
        _heard_by(transcript, "alice", DIFFICULTY, at=later)
        _heard_by(transcript, "bob", DIFFICULTY, at=earlier)

    assert earlier < later
    assert transcript.marks[-1] == Mark(t_ns=earlier + 1, label=OBSERVE_CLOSE)


async def _joined(context: GroupContext, name: str) -> Bot:
    bot = await context.bot(name)
    await bot.join()
    return bot


@pytest.mark.asyncio
async def test_until_with_bot_ends_the_window_at_that_bots_packet() -> None:
    # Audit 2026-10-02, L1: across Bots, arrival order is the order the readers ran, so
    # another Bot's packet stamped earlier must not end the window of the Bot named.
    transcript = Transcript(group_id="test/until", server="fake")
    async with playing(server([]), transcript) as context:
        alice = await _joined(context, "alice")
        await _joined(context, "bob")
        async with context.observe(until=DIFFICULTY, bot=alice):
            _heard_by(transcript, "bob", DIFFICULTY, at=transcript.now_ns())
            arrival = transcript.now_ns()
            _heard_by(transcript, "alice", DIFFICULTY, at=arrival)

    assert transcript.marks[-1] == Mark(t_ns=arrival + 1, label=OBSERVE_CLOSE)


@pytest.mark.asyncio
async def test_until_with_bot_fails_when_only_another_bot_got_the_packet() -> None:
    transcript = Transcript(group_id="test/until", server="fake")
    async with playing(server([]), transcript) as context:
        alice = await _joined(context, "alice")
        await _joined(context, "bob")
        with pytest.raises(ProtocolError, match=f"no {DIFFICULTY} arrived at alice"):
            async with context.observe(until=DIFFICULTY, bot=alice):
                _heard_by(transcript, "bob", DIFFICULTY, at=transcript.now_ns())


@pytest.mark.asyncio
async def test_bot_needs_until_and_one_of_the_groups_bots() -> None:
    transcript = Transcript(group_id="test/until", server="fake")
    async with playing(server([]), transcript) as context:
        alice = await _joined(context, "alice")
        with pytest.raises(ValueError, match="bot= names the Bot whose until packet"):
            async with context.observe(bot=alice):
                pass
        async with playing(server([]), Transcript(group_id="other", server="fake")) as other:
            stranger = await _joined(other, "carol")
            with pytest.raises(ValueError, match="not one of this Group's Bots"):
                async with context.observe(until=DIFFICULTY, bot=stranger):
                    pass

    assert transcript.marks == []


@pytest.mark.asyncio
async def test_the_window_is_over_after_a_missing_packet() -> None:
    transcript = Transcript(group_id="test/until", server="fake")
    async with playing(server([]), transcript) as context:
        with pytest.raises(ProtocolError):
            async with context.observe(until=BATCH_FINISHED):
                pass
        async with context.observe():
            pass

    labels = [mark.label for mark in transcript.marks]
    assert labels == [OBSERVE_OPEN, OBSERVE_OPEN, OBSERVE_CLOSE]  # no Bot's own close


async def _wait_for_a_block(context: GroupContext) -> None:
    bot = await context.bot("alice")
    await bot.join()
    async with context.observe(until=BLOCK_UPDATE):
        await bot.command("batch")
        await bot.sync()


WAITS = Group(id="test/until", run=_wait_for_a_block)


@pytest.mark.asyncio
async def test_a_candidate_that_never_sends_the_packet_fails_rather_than_errs() -> None:
    async with serve(CODEC, server([])) as endpoint:
        reference = await run_group(WAITS, endpoint, server="vanilla", timeout_s=2.0)
    async with serve(CODEC, server([], answers=False)) as endpoint:
        with pytest.raises(GroupError) as caught:
            await run_group(WAITS, endpoint, server="candidate", timeout_s=2.0)

    verdict = judge(WAITS, reference, caught.value)

    assert verdict.outcome is Outcome.MISMATCH, verdict
    failed = verdict.divergences[0]
    assert failed.kind == "failed", verdict
    assert BLOCK_UPDATE in str(failed.candidate), verdict


@pytest.mark.asyncio
async def test_a_reference_that_never_sends_the_packet_is_an_error() -> None:
    async with serve(CODEC, server([], answers=False)) as endpoint:
        with pytest.raises(GroupError) as caught:
            await run_group(WAITS, endpoint, server="vanilla", timeout_s=2.0)
    async with serve(CODEC, server([])) as endpoint:
        candidate = await run_group(WAITS, endpoint, server="candidate", timeout_s=2.0)

    verdict = judge(WAITS, caught.value, candidate)

    assert verdict.outcome is Outcome.ERROR, verdict
    assert BLOCK_UPDATE in (verdict.detail or ""), verdict


HELD_SLOT = "minecraft:set_held_slot"


def _heard_slot(transcript: Transcript, bot: str, *, at: int) -> None:
    packet_id = CODEC.packet_id(State.PLAY, Direction.CLIENTBOUND, HELD_SLOT)
    packet = CODEC.decode(State.PLAY, Direction.CLIENTBOUND, bytes([packet_id, 0]))
    transcript.record(bot, packet, t_ns=at)


@pytest.mark.asyncio
@pytest.mark.parametrize("first", [DIFFICULTY, HELD_SLOT])
async def test_until_several_names_closes_at_whichever_arrived_first(first: str) -> None:
    # A server may carry the same thing in another packet (Pumpkin's disguised_chat for
    # vanilla's player_chat, #270): the window ends on it too, and Compare shows the change.
    transcript = Transcript(group_id="test/until", server="fake")
    context = GroupContext(Endpoint(host="127.0.0.1", port=1), transcript, timeout_s=1.0)
    heard = {
        DIFFICULTY: lambda at: _heard_by(transcript, "alice", DIFFICULTY, at=at),
        HELD_SLOT: lambda at: _heard_slot(transcript, "alice", at=at),
    }
    second = HELD_SLOT if first == DIFFICULTY else DIFFICULTY

    async with context.observe(until=(DIFFICULTY, HELD_SLOT)):
        arrival = transcript.now_ns()
        heard[first](arrival)
        heard[second](transcript.now_ns())

    assert transcript.marks[-1] == Mark(t_ns=arrival + 1, label=OBSERVE_CLOSE)


@pytest.mark.asyncio
async def test_until_several_names_fails_naming_each_when_none_arrived() -> None:
    transcript = Transcript(group_id="test/until", server="fake")
    context = GroupContext(Endpoint(host="127.0.0.1", port=1), transcript, timeout_s=1.0)

    with pytest.raises(ProtocolError, match=f"no {DIFFICULTY} or {HELD_SLOT} arrived"):
        async with context.observe(until=(DIFFICULTY, HELD_SLOT)):
            pass


@pytest.mark.asyncio
async def test_until_checks_each_name_and_needs_one() -> None:
    transcript = Transcript(group_id="test/until", server="fake")
    context = GroupContext(Endpoint(host="127.0.0.1", port=1), transcript, timeout_s=1.0)

    with pytest.raises(ValueError, match="minecraft:hello"):
        async with context.observe(until=(DIFFICULTY, "minecraft:hello")):
            pass
    with pytest.raises(ValueError, match="at least one packet"):
        async with context.observe(until=()):
            pass
    with pytest.raises(ValueError, match="at least one packet"):
        async with context.observe(until=[]):  # ty: ignore[invalid-argument-type]
            pass

    assert transcript.marks == []


@pytest.mark.asyncio
async def test_a_narrowed_window_must_compare_every_packet_that_can_end_it() -> None:
    # Compare drops what `names` leaves out, so a Candidate ending the window on the other
    # packet would show no difference (#270 review): the window refuses to open instead.
    transcript = Transcript(group_id="test/until", server="fake")
    context = GroupContext(Endpoint(host="127.0.0.1", port=1), transcript, timeout_s=1.0)

    with pytest.raises(ValueError, match=f"add {DIFFICULTY}, {HELD_SLOT} to names"):
        async with context.observe(BLOCK_UPDATE, until=(DIFFICULTY, HELD_SLOT)):
            pass
    assert transcript.marks == []

    # Each of the ending packets in names: the Report shows which one came.
    async with context.observe(DIFFICULTY, HELD_SLOT, until=(DIFFICULTY, HELD_SLOT)):
        _heard_by(transcript, "alice", DIFFICULTY, at=transcript.now_ns())
    # One name, as before: a Candidate that never sends it fails ("no X arrived").
    async with context.observe(BLOCK_UPDATE, until=DIFFICULTY):
        _heard_by(transcript, "alice", DIFFICULTY, at=transcript.now_ns())
