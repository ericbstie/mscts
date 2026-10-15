"""Mob pathfinding Groups: how a zombie notices, reaches and attacks a player who stands still.

Each play joins a Bot of its own, puts it at a fixed place and has Control build the play's
layout. Then the world is frozen while Control summons the mobs, so that none of them moves
before the clock starts. Control reads the game time and steps the world a fixed number of
ticks (`tick step`): the play's tick budget. The Bot reads what the server sends it about the
mobs, and when something a sample is about arrives (the zombie's move, a `damage_event`, the
door's block change), Control reads the game time again. A sample is the number of ticks
between the two readings. A frozen world does not advance its game time, so the first tick the
mobs live is tick 1.

Every mob is summoned with NBT, which makes vanilla skip `Mob.finalizeSpawn`, where a summoned
zombie gets its random equipment, baby chance, left hand, door breaking and reinforcement chance
(`SummonCommand.createEntity`, 26.3 javap). It wears a leather helmet, so that it does not
burn in daylight, and keeps it, drops nothing and never despawns. Each mob is tagged, so the
play removes only its own. Mobs' AI draws on a random source of each mob, not the world seed,
so two Instances differ in every play: the samples are compared as distributions (#24).
"""

import contextlib
import math
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass

from mscts.bot import Bot
from mscts.codec.packets import Packet
from mscts.entities import Entity
from mscts.group import Control, GroupContext, GroupKind, group
from mscts.groups._world import CONTROL_AT, normal, remove_tagged_until_gone
from mscts.spec import CONTROL_PLAYER

_TAG = "mscts_mobs"
"""What every mob a play summons is tagged with, so that it removes only those."""

_ZOMBIE_NBT = (
    'PersistenceRequired:1b,DeathLootTable:"minecraft:empty",drop_chances:{head:0.0f},'
    'equipment:{head:{id:"minecraft:leather_helmet",count:1}}'
)
"""A zombie that never despawns, drops nothing, and wears a helmet it keeps: a zombie in
daylight burns unless its head is covered (`Zombie.aiStep`)."""

_IDLE_S = 1.0
"""How long the Bot waits for a packet before Control reads the game time to see whether the
tick budget has run out."""

_TIME_QUERY = "time query gametime"
_GAMETIME_KEY = b"commands.time.query.gametime"
_WITH = b"\x09\x00\x04with"
"""The `with` list of a translated text component, as network NBT: its arguments."""

_LONG, _INT, _STRING = 4, 3, 8
"""The NBT tag types a server may give the game time as: vanilla a Long, Pumpkin a String."""

_DAMAGE = "minecraft:damage_event"
_MOVES = (
    "minecraft:move_entity_pos",
    "minecraft:move_entity_pos_rot",
    "minecraft:entity_position_sync",
    "minecraft:teleport_entity",
)
"""The packets that tell a client where an entity has moved."""

type _Position = tuple[float, float, float]


def gametime(said: Iterable[Packet]) -> int:
    """The game time in the answer to `time query gametime` among the system chat in `said`.

    Raises:
        ValueError: None of `said` is that answer.
    """
    for packet in said:
        content = (packet.fields or {}).get("content")
        if isinstance(content, bytes) and _GAMETIME_KEY in content:
            value = _first_argument(content)
            if value is not None:
                return value
    msg = f"no answer to {_TIME_QUERY} among what the server said"
    raise ValueError(msg)


def _first_argument(content: bytes) -> int | None:
    """The first argument of the translated text component `content`, if it is a number."""
    at = content.find(_WITH)
    if at < 0:
        return None
    kind = content[at + len(_WITH)]
    value = content[at + len(_WITH) + 5 :]  # past the element type and the list's length
    if kind == _LONG:
        return int.from_bytes(value[:8], "big", signed=True)
    if kind == _INT:
        return int.from_bytes(value[:4], "big", signed=True)
    if kind == _STRING:
        size = int.from_bytes(value[:2], "big")
        text = value[2 : 2 + size].decode(errors="replace")
        return int(text) if text.lstrip("-").isdigit() else None
    return None


def _summon(entity: str, at: _Position, nbt: str) -> str:
    """The `/summon` of `entity` at `at`, facing west, with `nbt` and the tag."""
    x, y, z = at
    return f'summon minecraft:{entity} {x} {y} {z} {{{nbt},Rotation:[90f,0f],Tags:["{_TAG}"]}}'


@dataclass(frozen=True, slots=True)
class _Layout:
    """What one play sets up.

    Attributes:
        bot: The Bot's name before the play's number.
        bot_at: Where the Bot stands.
        summons: The mobs, summoned in the frozen world.
        build: The commands that place the play's blocks, before the world is frozen.
        clear: The commands that take them away again, once the mobs have gone.
    """

    bot: str
    bot_at: _Position
    summons: tuple[str, ...]
    build: tuple[str, ...] = ()
    clear: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Clock:
    """The ticks the world has run since the play's mobs were summoned, read through Control."""

    control: Control
    start: int

    async def ticks(self) -> int:
        """How many ticks the world has run since the start."""
        return gametime(await self.control.run(_TIME_QUERY)) - self.start


@contextlib.asynccontextmanager
async def _arena(context: GroupContext, layout: _Layout) -> AsyncIterator[Bot]:
    """Join the play's Bot, set `layout` up in a frozen world, and yield the Bot; undo it all.

    Control goes away first, so that no mob takes it for a target. Once the play is over, the
    mobs go, then anything they dropped (Pumpkin drops loot whatever the NBT and the game
    rule), and the Bot waits until it is told their bodies are gone; the blocks go last.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
        name = f"{layout.bot}{context.play}"
        bot = await context.bot(name)
        await bot.join()
        x, y, z = layout.bot_at
        await control.run(f"tp {name} {x} {y} {z}")
        for command in reversed(layout.clear):
            undo.push_async_callback(control.run, command)
        for command in layout.build:
            await control.run(command)
        undo.push_async_callback(remove_tagged_until_gone, control, _TAG, bot)
        undo.push_async_callback(control.run, "kill @e[type=minecraft:item]")
        undo.push_async_callback(control.run, f"kill @e[tag={_TAG}]")
        await context.freeze()
        for summon in layout.summons:
            await control.run(summon)
        await bot.sync()
        yield bot


async def _start(control: Control, budget: int) -> _Clock:
    """Read the game time, then let the frozen world run `budget` ticks; the play's clock."""
    clock = _Clock(control, gametime(await control.run(_TIME_QUERY)))
    await control.run(f"tick step {budget}")
    return clock


async def _next(bot: Bot, clock: _Clock, budget: int, names: tuple[str, ...]) -> Packet | None:
    """The next packet called one of `names` to arrive at `bot`; None once `budget` has run."""
    while True:
        try:
            return await bot.expect(*names, timeout_s=_IDLE_S)
        except TimeoutError:
            if await clock.ticks() >= budget:
                return None


def _hurts_the_bot(bot: Bot, packet: Packet) -> bool:
    """Whether `packet` is a `damage_event` of the Bot's own player: of no entity it tracks."""
    return packet.name == _DAMAGE and (packet.fields or {}).get("entity_id") not in bot.entities


@dataclass(frozen=True, slots=True)
class _Chase:
    """A zombie chasing the Bot, and the two ticks a play of it samples.

    Attributes:
        layout: What the play sets up; its only zombie chases the Bot.
        budget: How many ticks the world runs.
        waypoint: The name of the sample of the first tick the zombie is where `reached` says.
        reached: Whether the zombie, as the Bot last saw it, has got to the waypoint.
        hit: The name of the sample of the tick the zombie first hurts the Bot.
    """

    layout: _Layout
    budget: int
    waypoint: str
    reached: Callable[[Entity], bool]
    hit: str


async def _chase(context: GroupContext, chase: _Chase) -> None:
    """Play `chase`: sample when the zombie first gets to its waypoint, and when it first hits."""
    async with _arena(context, chase.layout) as bot:
        zombie = bot.entities.find("zombie").id
        clock = await _start(context.control, chase.budget)
        reached = False
        while (packet := await _next(bot, clock, chase.budget, (_DAMAGE, *_MOVES))) is not None:
            if _hurts_the_bot(bot, packet):
                context.sample(chase.hit, await clock.ticks())
                return
            if not reached and chase.reached(bot.entities[zombie]):
                reached = True
                context.sample(chase.waypoint, await clock.ticks())


# `mobs/chase-open`: a zombie 16 blocks from the Bot on open ground.

_OPEN = _Layout(
    bot="open",
    bot_at=(0.5, -60.0, 0.5),
    summons=(_summon("zombie", (16.5, -60.0, 0.5), _ZOMBIE_NBT),),
)

CHASE_TICKS = 300
"""The tick budget of a chase in the open: vanilla's zombie hits the Bot at about tick 150."""

_MOVED_WITHIN = 15.5
"""How near the Bot the zombie, summoned 16 blocks away, must be to have moved towards it."""


@group("mobs/chase-open", spec=normal, kind=GroupKind.STATISTICAL, runs=25)
async def chase_open(context: GroupContext) -> None:
    """Sample the tick the zombie is first half a block closer, and the tick it first hits."""
    await _chase(
        context,
        _Chase(
            layout=_OPEN,
            budget=CHASE_TICKS,
            waypoint="chase_open.moved",
            reached=lambda zombie: math.hypot(zombie.x - 0.5, zombie.z - 0.5) <= _MOVED_WITHIN,
            hit="chase_open.hit",
        ),
    )


# `mobs/chase-maze`: the same chase, with a fence between them that has one gap, 4.5 blocks
# north of the straight line. Fences are 1.5 blocks high: the zombie sees the Bot over the
# fence, and so goes for it, but cannot jump it.

_FENCE_X = 8
_MAZE = _Layout(
    bot="maze",
    bot_at=(0.5, -60.0, 0.5),
    summons=(_summon("zombie", (16.5, -60.0, 0.5), _ZOMBIE_NBT),),
    build=(
        f"fill {_FENCE_X} -60 -10 {_FENCE_X} -60 4 minecraft:oak_fence",
        f"fill {_FENCE_X} -60 6 {_FENCE_X} -60 10 minecraft:oak_fence",
    ),
    clear=(f"fill {_FENCE_X} -60 -10 {_FENCE_X} -60 10 minecraft:air",),
)

MAZE_TICKS = 400
"""The tick budget of a chase through the gap: vanilla's zombie hits the Bot at about tick 180."""

_IN_THE_GAP = _FENCE_X + 0.9
"""The zombie's x once it is in the gap: its edge, 0.3 blocks from its centre, is in the fence's
block, where only the gap lets it be."""


@group("mobs/chase-maze", spec=normal, kind=GroupKind.STATISTICAL, runs=20)
async def chase_maze(context: GroupContext) -> None:
    """Sample the tick the zombie first gets into the gap, and the tick it first hits."""
    await _chase(
        context,
        _Chase(
            layout=_MAZE,
            budget=MAZE_TICKS,
            waypoint="chase_maze.gap",
            reached=lambda zombie: zombie.x < _IN_THE_GAP,
            hit="chase_maze.hit",
        ),
    )
