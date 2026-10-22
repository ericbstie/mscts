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
from tests.net.fakes import EMPTY_CHUNK, NO_STATISTICS, TICK_S, JoinScript, Peer, join_server

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


@dataclass
class PlayerServer:
    """A fake server that joins like vanilla and answers Control's markers and the barrier.

    It answers a respawn request as `PlayerList.respawn` does: the `respawn` packet, then one
    chunk batch. After a `tp` in `hurts`, it hurts the Bot a tick later, and then once in
    each of that place's periods, until the next `tp` or `kill`: as on vanilla, a Bot moved or
    made fresh (`kill`, then respawn) is out of what hurt it.
    """

    seen: list[Packet] = field(default_factory=list)
    hurts: Mapping[str, int] = field(default_factory=dict)
    """Each `tp` after which the fake sends `set_health` and `entity_event`, and the ticks
    between two of them."""
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
            if command in self.hurts:
                self.hurting = asyncio.create_task(self._hurt(self.hurts[command]))

    def _stop_hurting(self) -> None:
        if self.hurting is not None:
            self.hurting.cancel()
            self.hurting = None

    async def _hurt(self, period_ticks: int) -> None:
        """Hurt every player but Control a tick from now, then every `period_ticks` ticks."""
        delay_s = TICK_S
        with suppress(ConnectionError):
            while True:
                await asyncio.sleep(delay_s)
                delay_s = period_ticks * TICK_S
                for name, peer in list(self.players.items()):
                    if name != CONTROL:
                        await peer.send(
                            "minecraft:set_health", health=19.0, food=20, saturation=5.0
                        )
                        await peer.send("minecraft:entity_event", entity_id=2, event_id=67)
