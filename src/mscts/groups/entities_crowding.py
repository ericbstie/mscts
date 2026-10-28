"""Crowding Groups: how mobs crowded into one place push each other, and how many it hurts.

A Bot called `watcher` stands at the spawn. Control, far away, summons pigs a few blocks from it,
overlapping, in a frozen world (`tick freeze`), and the world steps tick by tick. Every pig is
summoned with NBT, which makes vanilla skip what it draws at random for a new mob
(`SummonCommand.createEntity`, 26.3 javap). It cannot think (`NoAI`), drops nothing and is
tagged, so the Group removes only its own pigs. (Mobs do not spawn on their own: the Fixture
world has `spawn_mobs` off, ADR-0013.)

A pig that cannot think never moves: `LivingEntity.aiStep` runs `travel` only for a mob whose AI
runs (`Mob.isEffectiveAi`), but `pushEntities` still adds every push to its velocity. So the
watcher sees pushing as `set_entity_motion` alone, the same every tick, while the pigs stay
where they were summoned (26.3 javap, measured on #48).

Vanilla sends an entity's position every 60 of its tracker's ticks (`ServerEntity.sendChanges`),
which count in a frozen world too, so when a `move_entity_pos` comes follows the wall clock:
no window compares it.
"""

import contextlib
import math
from collections.abc import AsyncIterator, Sequence

from mscts.bot import Bot
from mscts.group import Control, GroupContext, GroupKind, group
from mscts.groups._world import CONTROL_AT, fast_forward, pin_joins, remove_tagged_until_gone
from mscts.spec import CONTROL_PLAYER

WATCHER = "watcher"
"""The Bot of `entities/pushing`, which is told about the pigs."""

_TAG = "mscts_crowding"
"""What every pig a Group summons is tagged with, so that it removes only those."""

_PIG_NBT = (
    'NoAI:1b,PersistenceRequired:1b,DeathLootTable:"minecraft:empty",Rotation:[90f,0f],'
    f'Tags:["{_TAG}"]'
)
"""A pig that cannot think, never despawns, drops nothing and faces west."""

_KILL_PIGS = f"kill @e[tag={_TAG}]"
_KILL_ITEMS = "kill @e[type=minecraft:item]"
"""Pumpkin drops a killed pig's porkchops whatever its loot table or `mob_drops` say."""

_FIXTURE_RULES = (("mob_griefing", "false", "true"), ("mob_drops", "false", "true"))
"""Each game rule the Fixture sets: its name, its value, and vanilla's default it goes back to."""

_DYING_TICKS = 20
"""How long a body stays: `LivingEntity.tickDeath` removes it once its `deathTime` reaches 20."""

_GONE_TICKS = _DYING_TICKS + 5
"""How far the world steps after a crowd dies: until the bodies are gone, and 5 ticks more."""

_Y = -60
"""The height the pigs stand at: on the grass of the flat world."""

type _Place = tuple[float, float]
"""An x and a z."""

type _Rule = tuple[str, str, str]
"""A game rule a Group sets: its name, its value, and the value it goes back to."""


def _summon(at: _Place) -> str:
    """The `/summon` of one of the Group's pigs at `at`."""
    x, z = at
    return f"summon minecraft:pig {x} {_Y} {z} {{{_PIG_NBT}}}"


@contextlib.asynccontextmanager
async def _arena(
    context: GroupContext, watcher: str, rules: Sequence[_Rule] = ()
) -> AsyncIterator[tuple[Bot, contextlib.AsyncExitStack]]:
    """Set the Fixture and `rules`, freeze the world and join `watcher`; undo it all after.

    Yields the watcher and the stack of undos, for what the body sets: they run first. Then the
    pigs go, and anything they dropped, and the watcher waits until it is told their bodies are
    gone; then the rules come back.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        await control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
        for rule, value, default in (*_FIXTURE_RULES, *rules):
            await control.run(f"gamerule {rule} {value}")
            undo.push_async_callback(control.run, f"gamerule {rule} {default}")
        await context.freeze()
        bot = await context.bot(watcher)
        await bot.join()
        undo.push_async_callback(remove_tagged_until_gone, control, _TAG, bot)
        undo.push_async_callback(control.run, _KILL_ITEMS)
        undo.push_async_callback(control.run, _KILL_PIGS)
        yield bot, undo


async def _clear(control: Control) -> None:
    """Kill the pigs and step the frozen world until their bodies are gone, then their drops."""
    await control.run(_KILL_PIGS)
    await fast_forward(control, _GONE_TICKS)
    await control.run(_KILL_ITEMS)


# `entities/pushing`: crowds of 2, 5 and 12 pigs, summoned overlapping in a 1 x 1 pen of oak
# fences and in the open.

PUSH_TICKS = 5
"""How many ticks each crowd pushes: the velocity grows by the same amount every tick."""

_PUSH_PACKETS = (
    "minecraft:bundle_delimiter",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:set_entity_motion",
    "minecraft:update_attributes",
    "minecraft:damage_event",
    "minecraft:entity_event",
    "minecraft:remove_entities",
)
"""What a window compares: the pigs appearing, their data and velocity, a hurt or a death, and
their removal."""

_CROWDS = (2, 5, 12)
_SPREAD = 0.2
"""How far from its crowd's centre each pig stands: a pig is 0.9 blocks wide, so they overlap."""

_PEN_AT: _Place = (4.5, 4.5)
_OPEN_AT: _Place = (10.5, 4.5)
_PEN = ("fill 3 -60 3 5 -60 5 minecraft:oak_fence", "setblock 4 -60 4 minecraft:air")
_PEN_CLEAR = "fill 3 -60 3 5 -60 5 minecraft:air"


def _ring(count: int, centre: _Place) -> list[_Place]:
    """`count` places `_SPREAD` from `centre`, evenly round it from the east, anticlockwise.

    Each is rounded to a thousandth, so no two pigs of a crowd share a place, and so a name.
    """
    cx, cz = centre
    angles = (2 * math.pi * i / count for i in range(count))
    return [
        (round(cx + _SPREAD * math.cos(angle), 3), round(cz + _SPREAD * math.sin(angle), 3))
        for angle in angles
    ]


async def _push(context: GroupContext, crowd: Sequence[_Place]) -> None:
    """Summon `crowd` and step `PUSH_TICKS` ticks in a window; kill it after the window."""
    async with context.observe(*_PUSH_PACKETS):
        for place in crowd:
            await context.control.run(_summon(place))
        await context.step(PUSH_TICKS)
    await _clear(context.control)


@group("entities/pushing", kind=GroupKind.TICK_EXACT)
async def pushing(context: GroupContext) -> None:
    """Each crowd is summoned in a window of its own, which steps the world `PUSH_TICKS` ticks."""
    control = context.control
    async with _arena(context, WATCHER) as (_, undo):
        undo.push_async_callback(control.run, _PEN_CLEAR)
        for command in _PEN:
            await control.run(command)
        for centre in (_PEN_AT, _OPEN_AT):
            for count in _CROWDS:
                await _push(context, _ring(count, centre))
