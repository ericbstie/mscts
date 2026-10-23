"""A fake server for the player Groups: it hurts, kills and respawns the Bot as vanilla does."""

import asyncio
import itertools
import json
from collections.abc import Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass, field

from mscts.bot import SYNC_REQUESTS
from mscts.codec.packets import Packet
from support.bot_join import ENTITY_ID, RESPAWN
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


DROWNING_DAMAGE = "gamerule drowning_damage "


HARMS = "minecraft:instant_damage 1 1 true"
"""How an `effect give` command that harms a Bot ends."""


@dataclass(frozen=True)
class Hurt:
    """How the fake hurts a Bot in a place: when the first hit comes, and how often.

    Attributes:
        period_ticks: The ticks between two hits.
        first_ticks: The ticks from the `tp` there to the first hit.
    """

    period_ticks: int
    first_ticks: int = 1


AIR_RUNS_OUT = 20
"""How far below 0 a drowning player's air goes before the first hit (`shouldTakeDrowningDamage`:
air <= -20)."""

DROWNING_HIT = 2.0
"""The damage of one drowning hit (`LivingEntity.baseTick`: `hurtServer(drown, 2.0)`)."""

HARM = 12.0
"""The damage `effect give <bot> minecraft:instant_damage 1 1 true` does: 6 << 1."""

FULL_HEALTH = 20.0

BUBBLES = 67
"""The entity event a drowning player's air reset sends (`broadcastEntityEvent(this, 67)`)."""

POOF = 60
"""The entity event a dead player is sent 20 ticks after its death (`LivingEntity.tickDeath`)."""

AIR_INDEX = 1
"""The entity data entry that holds an entity's air."""

INT = "int"
"""The entity data serializer of the air: a VarInt."""


@dataclass(frozen=True)
class Drown:
    """How the fake drowns a Bot put under water: its air runs down a point a tick.

    The air starts at `air` and goes down by one a tick, sent each tick in `set_entity_data`.
    The first time it reaches -`AIR_RUNS_OUT`, as on vanilla, the fake sends the bubbles
    (`entity_event` 67), and with `drowning_damage` on, a hit of `DROWNING_HIT`: the `set_health`,
    or the death once the health is gone. Then the air is 0 again, which the next
    `set_entity_data` says. Each later time comes `period_ticks` after the last.

    Attributes:
        period_ticks: The ticks between two times the air runs out after the first: vanilla's
            is `AIR_RUNS_OUT`.
        air: The air the Bot has when it is put under water; vanilla's is 300, which would make
            a play 15 s longer.
        other_event: An entity event that is not the bubbles, which the fake sends on the first
            tick under water if given: a near miss for a Group that waits for the bubbles.
        burst: How many ticks after the first time the air runs out come back to back, as on a
            server that runs the ticks it owes after it fell behind. With `AIR_RUNS_OUT` or
            more, the air runs out again before any command the Bot's bubbles prompt arrives.
    """

    period_ticks: int = AIR_RUNS_OUT
    air: int = 3
    other_event: int | None = None
    burst: int = 0


def _waits(drown: Drown) -> Iterator[float]:
    """The wall-clock wait before each tick of `drown`: none for the ticks of its burst."""
    yield from itertools.repeat(TICK_S, drown.air + AIR_RUNS_OUT)
    yield from itertools.repeat(0.0, drown.burst)
    yield from itertools.repeat(TICK_S)


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

    A place in `hurts` given as a `Drown` is different: the fake runs down the Bot's air a tick
    at a time on the wall clock, and never holds a hit back for a barrier.
    """

    seen: list[Packet] = field(default_factory=list)
    hurts: Mapping[str, Hurt | Drown] = field(default_factory=dict)
    """Each `tp` after which the fake sends `set_health` and `entity_event`, and when."""
    drowning_damage: bool = True
    """The game rule `drowning_damage`, which Control's `gamerule` sets."""
    health: float = FULL_HEALTH
    """The health of the Bot the fake drowns: full after a respawn, less after a harm or a hit."""
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
    before_respawn: tuple[tuple[str, Mapping[str, object]], ...] = ()
    """The packets, by name and fields, the fake sends just before each `respawn`: what vanilla
    has sent a dead player whose respawn request comes 20 ticks or more after its death is entity
    event 60 (`LivingEntity.tickDeath`), as if the Bot had stalled that long."""

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
                    self.health = FULL_HEALTH
                    for before, fields in self.before_respawn:
                        await peer.send(before, **fields)
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
            await self._kill(victim)
        elif command.startswith(DROWNING_DAMAGE):
            self.drowning_damage = command.removeprefix(DROWNING_DAMAGE) == "true"
        elif command.startswith("effect give ") and command.endswith(HARMS):
            victim = self.players[command.split()[2]]
            self.health -= HARM
            await victim.send("minecraft:set_health", health=self.health, food=20, saturation=5.0)
        elif command.startswith(("tp ", "kill ")):
            self._stop_hurting()  # moved or respawned, the Bot is out of what hurt it
            if command.startswith("tp "):
                await self._teleport(command)
            hurt = self.hurts.get(command)
            if isinstance(hurt, Drown):
                self.hurting = asyncio.create_task(self._drown(hurt))
            elif hurt is not None:
                self.hurting = asyncio.create_task(self._hurt(hurt))

    @staticmethod
    async def _kill(victim: Peer) -> None:
        await victim.write(victim.raw_frame(DEATH, b"\x02" + text("dead")))

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

    async def _drown(self, drown: Drown) -> None:
        """Drown every player but Control as `drown` says, a tick at a time, until one dies.

        A tick is `TICK_S` of the wall clock, as a player's is on vanilla: no barrier holds it.
        The ticks of a burst do not wait at all, so nothing else on the event loop runs between
        them.
        """
        air, runs_out = drown.air, AIR_RUNS_OUT
        with suppress(ConnectionError):
            if drown.other_event is not None:
                await asyncio.sleep(TICK_S)
                await self._to_bots(
                    "minecraft:entity_event", entity_id=ENTITY_ID, event_id=drown.other_event
                )
            for wait_s in _waits(drown):
                if wait_s:
                    await asyncio.sleep(wait_s)
                air -= 1
                if air <= -runs_out:
                    air, runs_out = 0, drown.period_ticks
                    killed = await self._air_runs_out()
                    if killed:
                        return
                await self._to_bots(
                    "minecraft:set_entity_data",
                    entity_id=ENTITY_ID,
                    entries=[{"index": AIR_INDEX, "serializer": INT, "value": air}],
                )

    async def _air_runs_out(self) -> bool:
        """Send the bubbles, and the hit if `drowning_damage` is on; True if it killed the Bot."""
        await self._to_bots("minecraft:entity_event", entity_id=ENTITY_ID, event_id=BUBBLES)
        if not self.drowning_damage:
            return False
        self.health -= DROWNING_HIT
        if self.health <= 0:
            for peer in self._bots():
                await self._kill(peer)
            return True
        await self._to_bots("minecraft:set_health", health=self.health, food=20, saturation=5.0)
        return False

    def _bots(self) -> list[Peer]:
        return [peer for name, peer in self.players.items() if name != CONTROL]

    async def _to_bots(self, name: str, **fields: object) -> None:
        for peer in self._bots():
            await peer.send(name, **fields)

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
