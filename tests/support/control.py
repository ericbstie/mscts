"""A fake server for a Group's Control, and the frames and constants the Group tests share."""

import asyncio
import json
import struct
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from mscts.bot import SYNC_REQUESTS
from mscts.codec.packets import Codec, Direction, Packet
from mscts.group import GroupContext
from mscts.target import TARGET
from mscts.transcript import Event, Transcript
from tests.net.fakes import (
    NO_STATISTICS,
    TICK_S,
    Handler,
    JoinScript,
    Peer,
    join_server,
    serve,
)

CHAT_COMMAND, SYSTEM_CHAT = "minecraft:chat_command", "minecraft:system_chat"
CONTROL = "control"
"""The name of the Bot a Group's Control is."""


CODEC = Codec.for_target(TARGET)


CLIENT_COMMAND = "minecraft:client_command"


AWARD_STATS = "minecraft:award_stats"


SETBLOCK = "setblock 1 -60 1 minecraft:stone"


FEEDBACK = "Changed the block at 1, -60, 1"


MARKER = "tellraw @s "


PLAY_TIMEOUT_S = 60.0
"""How long a fake serves a Bot: a whole play, which takes blocks/clone 2 to 4 s when the
host is idle and more than twice that under load (#209). It is below pytest's timeout, so
a hung fake still fails with where it hung."""


HANG_LIMIT_S = 1.5
"""The limit on one Bot operation in a test that expects a TimeoutError from a hang. Only the
hang may reach it: an idle host answers in about 0.1 s, and a stall (#410) is shorter."""


STALL_S = 0.7
"""How late a fake answers a command in a test of a stall: a loaded host. It is more than the
0.5 s limit these tests had and less than `HANG_LIMIT_S` (#419)."""


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
    write by `after_answer[n]` if there is one; an even one is answered a tick (`TICK_S`)
    later, so each barrier of two requests shows a tick between its answers, as vanilla's
    does. `on_command` is called with each command before it is answered. A command in
    `stalls` is answered, and everything after it, that many seconds late: a loaded host.
    Every serverbound Packet goes into `seen`.
    """

    seen: list[Packet] = field(default_factory=list)
    commands: Mapping[str, object] | None = field(default_factory=lambda: TREE)
    answers_markers: bool = True
    out_of_order: bool = False
    after_join: tuple[str, ...] = ()
    after_answer: Mapping[int, str] = field(default_factory=dict)
    new_commands: Mapping[str, object] | None = None
    on_command: Callable[[str], None] = lambda _: None
    rejoin_without_tree: bool = False
    stalls: Mapping[str, float] = field(default_factory=dict)
    _requests: int = field(default=0, init=False)
    _held: list[str] = field(default_factory=list, init=False)
    _connections: int = field(default=0, init=False)

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler.

        With `rejoin_without_tree`, every connection after the first joins with no
        command tree.
        """
        self._connections += 1
        commands = None if self._connections > 1 and self.rejoin_without_tree else self.commands
        await join_server(self.seen, JoinScript(commands=commands, then=self._play))(peer)

    async def _play(self, peer: Peer) -> None:
        for message in self.after_join:
            await peer.write(chat(peer, message))
        if self.new_commands is not None:
            await peer.send("minecraft:commands", **self.new_commands)
        async for packet in peer.packets():
            self.seen.append(packet)
            if packet.name == "minecraft:client_command":
                self._requests += 1
                if (self._requests - 1) % SYNC_REQUESTS != 0:
                    await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                straggler = self.after_answer.get(self._requests)
                said = b"" if straggler is None else chat(peer, straggler)
                await peer.write(peer.raw_frame(AWARD_STATS, NO_STATISTICS) + said)
            elif packet.name == CHAT_COMMAND:
                command = str((packet.fields or {})["command"])
                if command in self.stalls:
                    await asyncio.sleep(self.stalls[command])
                await peer.write(self._answer(peer, command))

    def _answer(self, peer: Peer, command: str) -> bytes:
        """What the server writes when `command` arrives: maybe nothing yet."""
        self.on_command(command)
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


def late(handler: Handler, delay_s: float) -> Handler:
    """A Handler that serves a connection `delay_s` late: a loaded host, from the join on."""

    async def delayed(peer: Peer) -> None:
        await asyncio.sleep(delay_s)
        await handler(peer)

    return delayed


@asynccontextmanager
async def playing(
    handler: Handler, transcript: Transcript, *, timeout_s: float = 2.0
) -> AsyncIterator[GroupContext]:
    """A GroupContext against a fake server running `handler`, closed however the body ends."""
    async with serve(CODEC, handler, timeout_s=PLAY_TIMEOUT_S) as endpoint:
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
