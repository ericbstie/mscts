"""Control: the operator Bot a Group sets the world up with, against a fake server."""

import asyncio
import time
from collections.abc import Mapping

import pytest
from support.control import (
    AWARD_STATS,
    CHAT_COMMAND,
    CLIENT_COMMAND,
    CODEC,
    FEEDBACK,
    HANG_LIMIT_S,
    SETBLOCK,
    STALL_S,
    SYSTEM_CHAT,
    TREE,
    ControlServer,
    commands_sent,
    contents,
    late,
    playing,
    received,
    text,
    tree,
)

from mscts.bot import SYNC_REQUESTS
from mscts.codec.packets import Direction, Packet, State
from mscts.compare import Outcome, compare
from mscts.group import CommandMissing, Group, GroupContext
from mscts.net import ProtocolError
from mscts.run import GroupError, judge, run_group
from mscts.transcript import Transcript
from tests.net import fakes
from tests.net.fakes import (
    TICK_S,
    Handler,
    JoinScript,
    Peer,
    join_server,
    serve,
)


@pytest.mark.asyncio
async def test_a_play_outlasts_the_budget_of_one_fake_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A Group's Bots stay connected for the whole play, which on a loaded host takes
    # longer than a fake gives one exchange (#209): here, a play 4 times that budget.
    monkeypatch.setattr(fakes, "HANDLER_TIMEOUT_S", TICK_S)
    transcript = Transcript(group_id="test/control", server="fake")
    async with playing(ControlServer(), transcript) as context:
        await context.control.run(SETBLOCK)
        await asyncio.sleep(4 * TICK_S)
        await context.control.run("tick freeze")


@pytest.mark.asyncio
async def test_a_stalled_command_is_answered_late() -> None:
    # #410: a loaded host answers one operation after the limit; the stall stands for it.
    transcript = Transcript(group_id="test/control", server="fake")
    async with playing(ControlServer(stalls={SETBLOCK: 0.2}), transcript) as context:
        await context.control.run("tick freeze")  # joins Control: not part of what is timed
        began = time.monotonic()
        await context.control.run(SETBLOCK)
        stalled_s = time.monotonic() - began

    assert stalled_s >= 0.2


@pytest.mark.asyncio
async def test_run_joins_once_and_sends_each_command_then_a_marker() -> None:
    seen: list[Packet] = []
    transcript = Transcript(group_id="test/control", server="fake")
    async with playing(ControlServer(seen), transcript) as context:
        await context.control.run(SETBLOCK)
        await context.control.run("tick freeze")

    hellos = [packet for packet in seen if packet.name == "minecraft:hello"]
    assert [(packet.fields or {})["name"] for packet in hellos] == ["control"]
    assert commands_sent(seen) == [
        SETBLOCK,
        'tellraw @s "mscts-barrier-1"',
        "tick freeze",
        'tellraw @s "mscts-barrier-2"',
    ]
    assert {event.bot for event in transcript.events} == {"control"}


@pytest.mark.asyncio
@pytest.mark.parametrize("out_of_order", [False, True], ids=["in order", "after the marker"])
async def test_run_returns_what_the_server_said_but_the_markers_answer(
    *, out_of_order: bool
) -> None:
    transcript = Transcript(group_id="test/control", server="fake")
    handler = ControlServer(out_of_order=out_of_order)
    async with playing(handler, transcript) as context:
        said = await context.control.run(SETBLOCK)
        silent = await context.control.run("tick freeze")

    assert contents(said) == [text(FEEDBACK)]
    assert silent == ()


@pytest.mark.asyncio
async def test_run_returns_what_arrived_until_the_barrier_ended() -> None:
    # The first SYNC_REQUESTS are the barrier after the join; the next is the run's first.
    handler = ControlServer(after_answer={SYNC_REQUESTS + 1: "said during the barrier"})
    transcript = Transcript(group_id="test/control", server="fake")
    async with playing(handler, transcript) as context:
        said = await context.control.run(SETBLOCK)

    assert contents(said) == [text(FEEDBACK), text("said during the barrier")]


@pytest.mark.asyncio
async def test_what_another_bot_receives_meanwhile_is_not_controls_answer() -> None:
    transcript = Transcript(group_id="test/control", server="fake")
    fields = {"content": text("to alice"), "overlay": False}
    elsewhere = CODEC.decode(
        State.PLAY,
        Direction.CLIENTBOUND,
        CODEC.encode(State.PLAY, Direction.CLIENTBOUND, SYSTEM_CHAT, fields),
    )

    def alice_hears(_: str) -> None:
        transcript.record("alice", elsewhere, t_ns=transcript.now_ns())

    async with playing(ControlServer(on_command=alice_hears), transcript) as context:
        said = await context.control.run(SETBLOCK)

    assert contents(said) == [text(FEEDBACK)]
    assert {event.bot for event in transcript.events if event.packet is elsewhere} == {"alice"}


@pytest.mark.asyncio
async def test_run_returns_after_the_barrier_that_follows_the_markers_answer() -> None:
    transcript = Transcript(group_id="test/control", server="fake")
    async with playing(ControlServer(), transcript) as context:
        await context.control.run(SETBLOCK)
        events = received(transcript)

    names = [event.packet.name for event in events]
    marker = names.index(SYSTEM_CHAT, names.index(SYSTEM_CHAT) + 1)
    assert events[marker].packet.payload.find(b"mscts-barrier-1") > 0
    assert names[marker + 1 :] == [AWARD_STATS] * SYNC_REQUESTS


@pytest.mark.asyncio
async def test_what_arrived_before_the_command_is_not_its_answer() -> None:
    joined = "control joined the game"
    straggler = "said after a barrier"
    # This request ends the first run's barrier: what comes with its answer is not taken
    # before the second run.
    handler = ControlServer(after_join=(joined,), after_answer={2 * SYNC_REQUESTS: straggler})
    transcript = Transcript(group_id="test/control", server="fake")
    async with playing(handler, transcript) as context:
        first = await context.control.run(SETBLOCK)
        second = await context.control.run(SETBLOCK)

    assert contents(first) == [text(FEEDBACK)]
    assert contents(second) == [text(FEEDBACK)]
    chats = [event.packet.payload for event in received(transcript)]
    assert any(text(joined) in payload for payload in chats)
    assert any(text(straggler) in payload for payload in chats)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("commands", "command", "root"),
    [
        (tree("setblock", "tellraw"), "tick freeze", "tick"),
        (tree("setblock", "tick"), SETBLOCK, "tellraw"),
    ],
    ids=["the command", "tellraw, which the marker needs"],
)
async def test_a_command_the_server_does_not_have_is_never_sent(
    commands: Mapping[str, object], command: str, root: str
) -> None:
    seen: list[Packet] = []
    transcript = Transcript(group_id="test/control", server="fake")
    async with playing(ControlServer(seen, commands=commands), transcript) as context:
        with pytest.raises(CommandMissing) as missing:
            await context.control.run(command)

    assert missing.value.root == root
    assert commands_sent(seen) == []


@pytest.mark.asyncio
async def test_the_last_command_tree_the_server_sent_is_the_one_that_counts() -> None:
    seen: list[Packet] = []
    handler = ControlServer(seen, commands=tree("tellraw"), new_commands=TREE)
    transcript = Transcript(group_id="test/control", server="fake")
    async with playing(handler, transcript) as context:
        await context.control.run("tick freeze")

    assert commands_sent(seen) == ["tick freeze", 'tellraw @s "mscts-barrier-1"']


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["", "/tick freeze", " tick freeze"])
async def test_a_command_starts_with_its_name_and_no_slash(command: str) -> None:
    transcript = Transcript(group_id="test/control", server="fake")
    async with playing(ControlServer(), transcript) as context:
        with pytest.raises(ValueError, match="a command starts with its name"):
            await context.control.run(command)

    assert transcript.events == []


@pytest.mark.asyncio
async def test_a_groups_own_bot_cannot_be_called_control() -> None:
    transcript = Transcript(group_id="test/control", server="fake")
    async with playing(ControlServer(), transcript) as context:
        with pytest.raises(ValueError, match=r"context\.control"):
            await context.bot("control")

    assert transcript.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "error"),
    [
        (ControlServer(answers_markers=False), TimeoutError),
        (ControlServer(commands=None), TimeoutError),
        (ControlServer(commands=tree("setblock", "tellraw", root_index=7)), ProtocolError),
    ],
    ids=["a marker never answered", "no command tree", "a broken command tree"],
)
async def test_what_goes_wrong_in_control_is_controls_failure(
    handler: Handler, error: type[Exception]
) -> None:
    transcript = Transcript(group_id="test/control", server="fake")
    async with playing(handler, transcript, timeout_s=0.5) as context:
        with pytest.raises(error) as caught:
            await context.control.run(SETBLOCK)

    assert context.raised_by(caught.value) == "control"


def closes(handler: Handler) -> tuple[Handler, asyncio.Event]:
    """`handler`, and an Event that is set once it has served a connection to its end."""
    closed = asyncio.Event()

    async def tracked(peer: Peer) -> None:
        try:
            await handler(peer)
        finally:
            closed.set()

    return tracked, closed


@pytest.mark.asyncio
async def test_leave_closes_the_bot_and_the_next_run_joins_a_new_one_behind_the_barrier() -> None:
    seen: list[Packet] = []
    transcript = Transcript(group_id="test/control", server="fake")
    handler, closed = closes(ControlServer(seen))
    async with playing(handler, transcript) as context:
        await context.control.run(SETBLOCK)
        await context.control.leave()
        await asyncio.wait_for(closed.wait(), timeout=2.0)  # the server saw it close
        await context.control.run("tick freeze")

    steps = [
        packet.name
        for packet in seen
        if packet.name in {"minecraft:hello", CLIENT_COMMAND, CHAT_COMMAND}
    ]
    hello, barrier = "minecraft:hello", [CLIENT_COMMAND] * SYNC_REQUESTS
    run = [CHAT_COMMAND, CHAT_COMMAND, *barrier]  # the command, its marker, the barrier
    assert steps == [hello, *barrier, *run, hello, *barrier, *run]
    assert commands_sent(seen) == [
        SETBLOCK,
        'tellraw @s "mscts-barrier-1"',
        "tick freeze",
        'tellraw @s "mscts-barrier-2"',
    ]
    assert {event.bot for event in transcript.events} == {"control"}


@pytest.mark.asyncio
async def test_leave_before_control_has_joined_connects_nothing() -> None:
    seen: list[Packet] = []
    transcript = Transcript(group_id="test/control", server="fake")
    async with playing(ControlServer(seen), transcript) as context:
        await context.control.leave()
        await context.control.leave()

    assert seen == []
    assert transcript.events == []


@pytest.mark.asyncio
async def test_a_control_bot_that_is_still_open_is_never_replaced() -> None:
    # A join the server cut short leaves its Bot open and not yet Control's: a second run
    # must not connect over it, or the first would never be closed.
    transcript = Transcript(group_id="test/control", server="fake")
    handler = join_server([], JoinScript(disconnect_in=State.PLAY))
    async with playing(handler, transcript) as context:
        with pytest.raises(ProtocolError):
            await context.control.run(SETBLOCK)
        with pytest.raises(ValueError, match="already has a Bot called 'control'"):
            await context.control.run(SETBLOCK)


@pytest.mark.asyncio
async def test_a_rejoined_control_needs_the_tree_its_own_join_sent() -> None:
    seen: list[Packet] = []
    transcript = Transcript(group_id="test/control", server="fake")
    # #419: the only TimeoutError is the wait for the tree. The first run is slow, as on a
    # loaded host, and finishes within the limit; the second join is the one that hangs.
    server = ControlServer(seen, rejoin_without_tree=True, stalls={SETBLOCK: STALL_S})
    async with playing(server, transcript, timeout_s=HANG_LIMIT_S) as context:
        await context.control.run(SETBLOCK)
        await context.control.leave()
        with pytest.raises(TimeoutError) as caught:
            await context.control.run(SETBLOCK)

    assert context.raised_by(caught.value) == "control"
    assert commands_sent(seen) == [SETBLOCK, 'tellraw @s "mscts-barrier-1"']
    assert [packet.name for packet in seen].count("minecraft:hello") == 2, "Control never rejoined"


async def _setblock(context: GroupContext) -> None:
    await context.control.run(SETBLOCK)


SETS_A_BLOCK = Group(id="test/sets-a-block", run=_setblock)


@pytest.mark.asyncio
async def test_a_candidate_that_never_answers_the_marker_fails_the_group() -> None:
    async with serve(CODEC, ControlServer()) as endpoint:
        reference = await run_group(SETS_A_BLOCK, endpoint, server="vanilla", timeout_s=2.0)
    # #419: the only TimeoutError is the wait for the marker's answer. The join before it is
    # slow, as on a loaded host: it finishes within the limit, and the marker is sent.
    seen: list[Packet] = []
    silent = ControlServer(seen, answers_markers=False)
    async with serve(CODEC, late(silent, STALL_S)) as endpoint:
        with pytest.raises(GroupError) as caught:
            await run_group(SETS_A_BLOCK, endpoint, server="candidate", timeout_s=HANG_LIMIT_S)

    assert commands_sent(seen) == [SETBLOCK, 'tellraw @s "mscts-barrier-1"'], (
        "the marker was never sent"
    )
    verdict = judge(SETS_A_BLOCK, reference, caught.value)

    assert verdict.outcome is Outcome.MISMATCH, verdict
    failed = verdict.divergences[0]
    assert (failed.kind, failed.bot) == ("failed", "control"), verdict
    assert str(failed.candidate).startswith("TimeoutError"), verdict


@pytest.mark.asyncio
async def test_a_candidate_without_the_command_fails_the_group_needing_it() -> None:
    async with serve(CODEC, ControlServer()) as endpoint:
        reference = await run_group(SETS_A_BLOCK, endpoint, server="vanilla", timeout_s=2.0)
    async with serve(CODEC, ControlServer(commands=tree("tellraw"))) as endpoint:
        with pytest.raises(GroupError) as caught:
            await run_group(SETS_A_BLOCK, endpoint, server="candidate", timeout_s=2.0)

    verdict = judge(SETS_A_BLOCK, reference, caught.value)

    assert (verdict.outcome, verdict.detail) == (
        Outcome.MISMATCH,
        "the Candidate failed: missing /setblock",
    ), verdict
    failed = verdict.divergences[0]
    assert (failed.kind, failed.candidate) == ("failed", "missing /setblock"), verdict
    own = compare(reference, reference, SETS_A_BLOCK.masks).test_cases
    assert set(own) <= set(verdict.test_cases)
