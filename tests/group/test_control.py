"""Control: the operator Bot a Group sets the world up with, against a fake server."""

import json
import struct
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import pytest

from mscts.codec.packets import Codec, Direction, Packet
from mscts.compare import Outcome
from mscts.group import CommandMissing, Group, GroupContext
from mscts.net import ProtocolError
from mscts.run import GroupError, judge, run_group
from mscts.target import TARGET
from mscts.transcript import Event, Transcript
from tests.net.fakes import (
    NO_STATISTICS,
    Handler,
    JoinScript,
    Peer,
    join_server,
    serve,
)

CODEC = Codec.for_target(TARGET)
CHAT_COMMAND, SYSTEM_CHAT = "minecraft:chat_command", "minecraft:system_chat"
AWARD_STATS = "minecraft:award_stats"
SETBLOCK = "setblock 1 -60 1 minecraft:stone"
FEEDBACK = "Changed the block at 1, -60, 1"
MARKER = "tellraw @s "


def tree(*roots: str, root_index: int = 0) -> dict[str, object]:
    """A command tree whose root has a literal child for each of `roots`."""
    blank = {
        "children": [],
        "redirect_node": None,
        "parser": None,
        "properties": None,
        "suggestions_type": None,
    }
    root = blank | {"flags": 0, "name": None, "children": list(range(1, len(roots) + 1))}
    literals = [blank | {"flags": 0x05, "name": name} for name in roots]
    return {"nodes": [root, *literals], "root_index": root_index}


TREE = tree("setblock", "tellraw", "tick")


def text(content: str) -> bytes:
    """A text component as network NBT: a String tag holding `content`."""
    data = content.encode()
    return bytes([0x08]) + struct.pack(">H", len(data)) + data


def feedback(command: str) -> list[str]:
    """What the fake server says to a command other than a marker: setblock answers."""
    return [FEEDBACK] if command.startswith("setblock") else []


def chat(peer: Peer, message: str) -> bytes:
    """A system_chat frame saying `message`."""
    return peer.frame(SYSTEM_CHAT, content=text(message), overlay=False)


@dataclass
class ControlServer:
    """A fake server that joins like vanilla, then answers like a vanilla operator's server.

    It joins sending `commands` as the command tree. Then it says `after_join`, before
    anything is read, and sends `new_commands` as a new tree (as vanilla does when a
    player's operator level changes). A marker (`tellraw @s "<token>"`) gets the token
    back as a system_chat, unless `answers_markers` is False; any other command gets its
    `feedback`, or, if `out_of_order`, gets it after the next marker's answer, as Pumpkin
    often does. The n-th statistics request gets an award_stats, followed in the same
    write by `after_answer[n]` if there is one. Every serverbound Packet goes into `seen`.
    """

    seen: list[Packet] = field(default_factory=list)
    commands: Mapping[str, object] | None = field(default_factory=lambda: TREE)
    answers_markers: bool = True
    out_of_order: bool = False
    after_join: tuple[str, ...] = ()
    after_answer: Mapping[int, str] = field(default_factory=dict)
    new_commands: Mapping[str, object] | None = None
    _requests: int = field(default=0, init=False)
    _held: list[str] = field(default_factory=list, init=False)

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        await join_server(self.seen, JoinScript(commands=self.commands, then=self._play))(peer)

    async def _play(self, peer: Peer) -> None:
        for message in self.after_join:
            await peer.write(chat(peer, message))
        if self.new_commands is not None:
            await peer.send("minecraft:commands", **self.new_commands)
        async for packet in peer.packets():
            self.seen.append(packet)
            if packet.name == "minecraft:client_command":
                self._requests += 1
                straggler = self.after_answer.get(self._requests)
                said = b"" if straggler is None else chat(peer, straggler)
                await peer.write(peer.raw_frame(AWARD_STATS, NO_STATISTICS) + said)
            elif packet.name == CHAT_COMMAND:
                await peer.write(self._answer(peer, str((packet.fields or {})["command"])))

    def _answer(self, peer: Peer, command: str) -> bytes:
        """What the server writes when `command` arrives: maybe nothing yet."""
        if not command.startswith(MARKER):
            self._held += feedback(command)
            if self.out_of_order:
                return b""
        elif self.answers_markers:
            self._held.insert(0, json.loads(command.removeprefix(MARKER)))
        else:
            return b""
        frames = b"".join(chat(peer, message) for message in self._held)
        self._held.clear()
        return frames


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


def commands_sent(seen: list[Packet]) -> list[object]:
    return [(packet.fields or {})["command"] for packet in seen if packet.name == CHAT_COMMAND]


def contents(packets: tuple[Packet, ...]) -> list[object]:
    return [(packet.fields or {})["content"] for packet in packets]


def received(transcript: Transcript, bot: str = "control") -> list[Event]:
    return [
        event
        for event in transcript.events
        if event.bot == bot and event.packet.direction is Direction.CLIENTBOUND
    ]


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
    # Requests 1 and 2 are the barrier after the join; 3 is the first of the run's.
    handler = ControlServer(after_answer={3: "said during the barrier"})
    transcript = Transcript(group_id="test/control", server="fake")
    async with playing(handler, transcript) as context:
        said = await context.control.run(SETBLOCK)

    assert contents(said) == [text(FEEDBACK), text("said during the barrier")]


@pytest.mark.asyncio
async def test_run_returns_after_the_barrier_that_follows_the_markers_answer() -> None:
    transcript = Transcript(group_id="test/control", server="fake")
    async with playing(ControlServer(), transcript) as context:
        await context.control.run(SETBLOCK)
        events = received(transcript)

    names = [event.packet.name for event in events]
    marker = names.index(SYSTEM_CHAT, names.index(SYSTEM_CHAT) + 1)
    assert events[marker].packet.payload.find(b"mscts-barrier-1") > 0
    assert names[marker + 1 :] == [AWARD_STATS, AWARD_STATS]


@pytest.mark.asyncio
async def test_what_arrived_before_the_command_is_not_its_answer() -> None:
    joined = "control joined the game"
    straggler = "said after a barrier"
    # Request 4 ends the first run's barrier: what comes with its answer is not taken
    # before the second run.
    handler = ControlServer(after_join=(joined,), after_answer={4: straggler})
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


async def _setblock(context: GroupContext) -> None:
    await context.control.run(SETBLOCK)


SETS_A_BLOCK = Group(id="test/sets-a-block", run=_setblock)


@pytest.mark.asyncio
async def test_a_candidate_that_never_answers_the_marker_fails_the_group() -> None:
    async with serve(CODEC, ControlServer()) as endpoint:
        reference = await run_group(SETS_A_BLOCK, endpoint, server="vanilla", timeout_s=2.0)
    async with serve(CODEC, ControlServer(answers_markers=False)) as endpoint:
        with pytest.raises(GroupError) as caught:
            await run_group(SETS_A_BLOCK, endpoint, server="candidate", timeout_s=0.5)

    verdict = judge(SETS_A_BLOCK, reference, caught.value)

    assert verdict.outcome is Outcome.MISMATCH, verdict
    failed = verdict.divergences[0]
    assert (failed.kind, failed.bot) == ("failed", "control"), verdict
    assert str(failed.candidate).startswith("TimeoutError"), verdict


@pytest.mark.asyncio
async def test_a_candidate_without_the_command_blocks_the_group() -> None:
    async with serve(CODEC, ControlServer()) as endpoint:
        reference = await run_group(SETS_A_BLOCK, endpoint, server="vanilla", timeout_s=2.0)
    async with serve(CODEC, ControlServer(commands=tree("tellraw"))) as endpoint:
        with pytest.raises(GroupError) as caught:
            await run_group(SETS_A_BLOCK, endpoint, server="candidate", timeout_s=2.0)

    verdict = judge(SETS_A_BLOCK, reference, caught.value)

    assert (verdict.outcome, verdict.detail) == (Outcome.BLOCKED, "needs /setblock"), verdict
