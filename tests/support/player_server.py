"""A fake server for the player Groups: it hurts, kills and respawns the Bot as vanilla does."""

import asyncio
import json
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field

from mscts.bot import SYNC_REQUESTS
from mscts.codec.packets import Packet
from support.bot_join import RESPAWN
from support.control import CHAT_COMMAND, CLIENT_COMMAND, CONTROL, MARKER, text, tree
from support.gametime import gametime_answer
from tests.net.fakes import (
    EMPTY_CHUNK,
    NO_STATISTICS,
    SPAWN,
    TICK_S,
    JoinScript,
    Peer,
    join_server,
)

PERFORM_RESPAWN = 0


COMMANDS = tree(
    "gamerule", "tp", "tick", "setblock", "effect", "fill", "kill", "tellraw", "weather", "time"
)


TIME_QUERY = "time query gametime"


FADE_TICKS = 100
"""How far the fake's game time moves on between two reads: as far as a storm takes to fade."""


FADE_READS = (TIME_QUERY, TIME_QUERY)
"""Control reads the game time when the weather is cleared, and once the world has run on."""


DEATH = "minecraft:player_combat_kill"


@dataclass(frozen=True)
class Hurt:
    """How the fake hurts a Bot in a place: when the first hit comes, and how often.

    Attributes:
        period_ticks: The ticks between two hits.
        first_ticks: The ticks from the `tp` there to the first hit.
    """

    period_ticks: int
    first_ticks: int = 1


@dataclass
class PlayerServer:
    """A fake server that joins like vanilla and answers Control's markers and the barrier.

    It answers a respawn request as `PlayerList.respawn` does: the `respawn` packet, then one
    chunk batch. After a `tp` in `hurts`, it hurts the Bot when that place's first hit is due,
    and then once in each of its periods, until the next `tp` or `kill`: as on vanilla, a Bot
    moved or made fresh (`kill`, then respawn) is out of what hurt it.

    A hit is due on the wall clock, as on vanilla, but it is sent only once the Bot has passed a
    barrier since the hit before it: the barrier that opens the window that waits for it. So the
    order of a hit and the windows does not depend on the event loop being on time. On vanilla a
    window that opens too late lets the hit through between two windows, which the Group fails
    on (`check_gap`); the clock these tests give it (`always_on_time`) says the windows are on
    time, and the fake keeps to that. What the Group does after a hit, before the next window
    opens, still races the next hit, as on vanilla.
    """

    seen: list[Packet] = field(default_factory=list)
    hurts: Mapping[str, Hurt] = field(default_factory=dict)
    """Each `tp` after which the fake sends `set_health` and `entity_event`, and when."""
    due_at_once: bool = False
    """Whether every hit is due at once, as if the event loop had stalled past each one: it is
    then sent as soon as the Bot has passed the barrier."""
    barrier_since_hit: asyncio.Event = field(default_factory=asyncio.Event)
    """Set once a Bot but Control has passed a barrier since the last hit."""
    hurting: asyncio.Task[None] | None = None
    """The task that hurts the Bot, while it is somewhere that hurts."""
    kills_after: str | None = None
    """A command after which the fake sends `player_combat_kill`, once."""
    players: dict[str, Peer] = field(default_factory=dict)
    """Each connected player's connection, by name."""
    late: frozenset[str] = frozenset()
    """The players whose statistics requests are each answered a tick later still."""
    game_time: int = 0
    """The game time the next `time query gametime` answers: each answer moves it on by
    `FADE_TICKS`."""
    teleports: int = 0
    """How many `player_position` the fake has sent: the last teleport id."""
    held: bool = True
    """Whether each hit waits for a barrier since the last; False sends it when it is due."""

    def __post_init__(self) -> None:
        """No hit has come yet, so the first is not held back."""
        self.barrier_since_hit.set()

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=COMMANDS, then=self._play))(peer)

    async def _play(self, peer: Peer) -> None:
        requests = 0
        hellos = [p for p in self.seen if p.name == "minecraft:hello"]
        name = str((hellos[-1].fields or {})["name"])
        self.players[name] = peer
        try:
            async for packet in peer.packets():
                self.seen.append(packet)
                if packet.name == CLIENT_COMMAND and packet.fields == {"action": PERFORM_RESPAWN}:
                    await peer.send("minecraft:respawn", **RESPAWN, data_kept=0)
                    await peer.send("minecraft:chunk_batch_start")
                    await peer.send("minecraft:level_chunk_with_light", **EMPTY_CHUNK)
                    await peer.send("minecraft:chunk_batch_finished", batch_size=1)
                elif packet.name == CLIENT_COMMAND:
                    requests += 1
                    if (requests - 1) % SYNC_REQUESTS != 0:
                        await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                    if name in self.late:
                        await asyncio.sleep(TICK_S)
                    await peer.write(peer.raw_frame("minecraft:award_stats", NO_STATISTICS))
                    if name != CONTROL and requests % SYNC_REQUESTS == 0:
                        self.barrier_since_hit.set()
                elif packet.name == CHAT_COMMAND:
                    command = str((packet.fields or {})["command"])
                    await self._command(peer, command)
        finally:
            self._stop_hurting()

    async def _command(self, peer: Peer, command: str) -> None:
        """Answer `command` from `peer`."""
        if command.startswith(MARKER):
            token = json.loads(command.removeprefix(MARKER))
            await peer.write(
                peer.frame("minecraft:system_chat", content=text(token), overlay=False)
            )
        elif command == TIME_QUERY:
            answer = gametime_answer(self.game_time)
            self.game_time += FADE_TICKS
            await peer.write(peer.frame("minecraft:system_chat", content=answer, overlay=False))
        elif self.kills_after and command.startswith(self.kills_after):
            victim = self.players[command.split()[1]]
            await victim.write(victim.raw_frame(DEATH, b"\x02" + text("dead")))
        elif command.startswith(("tp ", "kill ")):
            self._stop_hurting()  # moved or respawned, the Bot is out of what hurt it
            if command.startswith("tp "):
                await self._teleport(command)
            if command in self.hurts:
                self.hurting = asyncio.create_task(self._hurt(self.hurts[command]))

    async def _teleport(self, command: str) -> None:
        """Send the player a `tp` moves its `player_position`, as vanilla does when it runs it."""
        _, name, *at = command.split()
        peer = self.players.get(name)
        if peer is not None:
            self.teleports += 1
            x, y, z = (float(part) for part in at)
            await peer.send(
                "minecraft:player_position",
                **{**SPAWN, "x": x, "y": y, "z": z},
                teleport_id=self.teleports,
                velocity_x=0.0,
                velocity_y=0.0,
                velocity_z=0.0,
                flags=0,
            )

    def _stop_hurting(self) -> None:
        if self.hurting is not None:
            self.hurting.cancel()
            self.hurting = None

    async def _hurt(self, hurt: Hurt) -> None:
        """Hurt every player but Control as `hurt` says, each hit after a barrier since the last."""
        ticks = hurt.first_ticks
        with suppress(ConnectionError):
            while True:
                await asyncio.sleep(0 if self.due_at_once else ticks * TICK_S)
                if self.held:
                    await self.barrier_since_hit.wait()
                self.barrier_since_hit.clear()
                ticks = hurt.period_ticks
                for name, peer in list(self.players.items()):
                    if name != CONTROL:
                        await peer.send(
                            "minecraft:set_health", health=19.0, food=20, saturation=5.0
                        )
                        await peer.send("minecraft:entity_event", entity_id=2, event_id=67)
