"""A fake server that answers a blocks Group's builder and Control like one run by operators."""

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass, field

from mscts.bot import SYNC_REQUESTS, TICK_GAP_S
from mscts.codec.packets import Direction, Packet
from mscts.groups import blocks
from mscts.transcript import Transcript
from support.control import AWARD_STATS, CHAT_COMMAND, CLIENT_COMMAND, CONTROL, MARKER, chat, tree
from tests.net.fakes import NO_STATISTICS, JoinScript, Peer, join_server

TICK_S = 2 * TICK_GAP_S
"""The fake's tick: just over what a barrier needs to see one pass, so a play is quick."""


COMMANDS = tree("setblock", "fill", "clone", "data", "tellraw", "tick", "gamerule", "kill", "tp")


@dataclass
class BlocksServer:
    """A fake server that joins like vanilla and answers commands like one run by operators.

    A marker (`tellraw @s "<token>"`) gets its token back at once. Any other command gets
    feedback, `feedback_after_s` later and while the server goes on answering the barrier
    (a server behind schedule), unless `feedback` is False. With `broadcast`, each command
    Control sends is also told to the builder, as vanilla tells every other operator.
    """

    seen: list[Packet] = field(default_factory=list)
    feedback: bool = True
    feedback_after_s: float = 0.0
    broadcast: bool = False
    _builder: Peer | None = field(default=None, init=False)

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        # A Bot that leaves with something unread (a late answer, or what Control said
        # last) resets the connection instead of closing it, and `join_server` reads on.
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=COMMANDS, then=self._play))(peer)

    def _player(self) -> str:
        hellos = [packet for packet in self.seen if packet.name == "minecraft:hello"]
        return str((hellos[-1].fields or {})["name"])

    async def _play(self, peer: Peer) -> None:
        player = self._player()
        if player == blocks.BUILDER:
            self._builder = peer
        requests = 0
        feedbacks: list[asyncio.Task[None]] = []
        async with asyncio.TaskGroup() as later:
            try:
                async for packet in peer.packets():
                    self.seen.append(packet)
                    if packet.name == CLIENT_COMMAND:
                        requests += 1
                        if (requests - 1) % SYNC_REQUESTS != 0:
                            await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                        await peer.write(peer.raw_frame(AWARD_STATS, NO_STATISTICS))
                    elif packet.name == CHAT_COMMAND:
                        command = str((packet.fields or {})["command"])
                        message = await self._answer(peer, player, command)
                        if message is not None:
                            feedbacks.append(later.create_task(self._say(peer, message)))
            except ConnectionError:
                pass  # the Bot left with something unread (a reset), or the builder did
            finally:
                for feedback in feedbacks:  # the Bot has gone: nobody is left to tell
                    feedback.cancel()

    async def _answer(self, peer: Peer, player: str, command: str) -> str | None:
        """Answer a marker, or tell the builder what Control did; return the feedback, if any."""
        if command.startswith(MARKER):
            await peer.write(chat(peer, json.loads(command.removeprefix(MARKER))))
            return None
        if self.broadcast and player == CONTROL and self._builder is not None:
            await self._builder.write(chat(self._builder, f"[control: {command}]"))
        return f"done: {command}" if self.feedback else None

    async def _say(self, peer: Peer, message: str) -> None:
        await asyncio.sleep(self.feedback_after_s)
        with suppress(ConnectionError):  # the Bot may have left first
            await peer.write(chat(peer, message))


def sent(transcript: Transcript, bot: str) -> list[tuple[int, str]]:
    """The commands `bot` sent, with when, but Control's markers."""
    commands = [
        (event.t_ns, str((event.packet.fields or {})["command"]))
        for event in transcript.events
        if event.bot == bot
        and event.packet.direction is Direction.SERVERBOUND
        and event.packet.name == CHAT_COMMAND
    ]
    return [(t_ns, command) for t_ns, command in commands if not command.startswith(MARKER)]
