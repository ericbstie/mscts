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


# `entities/cramming`: 30 pigs in one block space. A mob that touches more than
# `max_entity_cramming` - 1 other pushable entities takes 6 `cramming` damage, but only on a
# tick its own random source draws `nextInt(4) == 0` (`LivingEntity.pushEntities`, 26.3 javap),
# and a rule of 0 or less turns it off. That source is no world seed, so which pigs are hit,
# and when, differs on every play: the samples are compared as distributions (#24). A hit pig
# ignores another equal hit for 10 ticks (`LivingEntity.hurtServer`), so a pig of 10 health
# dies at its second hit, 10 ticks or more after its first. Once 6 have died, the 24 left each
# touch 23 others, and no more are hurt.
#
# The watcher reads each pig's health from the entity data it was sent (`_HEALTH`). Pumpkin
# sends none when a pig appears, so a pig with none is at full health.

CRAMMING_RUNS = 20
"""How many times `entities/cramming` plays on each server."""

_CRAM_AT: _Place = (8.5, 12.5)
_CRAM_GAP = 0.08
_CRAM_ROWS, _CRAM_COLUMNS = 5, 6
"""The 30 pigs stand in 5 rows of 6, 0.08 blocks apart, round `_CRAM_AT`."""

_CRAMMING_RULE = "max_entity_cramming"
_CRAMMING_LIMIT = 24
"""Vanilla's default `max_entity_cramming`, which the play turns back on after the rule is off."""

OFF_TICKS = 10
"""How many ticks the crowd stands with cramming off (`max_entity_cramming` 0)."""

_FIRST_TICKS = 10
"""The ticks with cramming on that `cramming.hurt_by_tick_10` covers: no pig has been hurt twice
yet, so none has died."""

CRAMMING_TICKS = 20
"""How many ticks the crowd stands with cramming on: vanilla's last death comes by tick 15
(measured on #48: 40 plays, ticks 11 to 15)."""

_PIG = "minecraft:pig"
_HEALTH = 9
"""The index of a living entity's health in its entity data: `LivingEntity.DATA_HEALTH_ID`, the
second it defines after the 8 of `Entity` (26.3 javap); vanilla and Pumpkin send it there."""

_PIG_HEALTH = 10.0
"""A pig's full health."""


def _grid(centre: _Place) -> list[_Place]:
    """`_CRAM_ROWS` rows of `_CRAM_COLUMNS` places centred on `centre`, from the north-west.

    The rows run west to east, `_CRAM_GAP` apart; each place is rounded to a thousandth.
    """
    return [
        _offset(centre, column - (_CRAM_COLUMNS - 1) / 2, row - (_CRAM_ROWS - 1) / 2)
        for row in range(_CRAM_ROWS)
        for column in range(_CRAM_COLUMNS)
    ]


def _offset(centre: _Place, east: float, south: float) -> _Place:
    """The place `east` and `south` gaps of `_CRAM_GAP` from `centre`, to a thousandth."""
    cx, cz = centre
    return (round(cx + east * _CRAM_GAP, 3), round(cz + south * _CRAM_GAP, 3))


def _healths(watcher: Bot) -> list[float]:
    """The health of each pig `watcher` tracks: full if the server has sent it none."""
    pigs = (entity for entity in watcher.entities.values() if entity.type == _PIG)
    return [_health(pig.data.get(_HEALTH)) for pig in pigs]


def _health(value: object) -> float:
    """A pig's health from its entity data's `value`: full if it is not a number."""
    return float(value) if isinstance(value, float | int) else _PIG_HEALTH


def _hurt(healths: Sequence[float]) -> int:
    """How many of `healths` are below a pig's full health, the dead included."""
    return sum(health < _PIG_HEALTH for health in healths)


def _dead(healths: Sequence[float]) -> int:
    """How many of `healths` are 0 or less."""
    return sum(health <= 0 for health in healths)


async def _run_on(control: Control, watcher: Bot, ticks: int) -> None:
    """Step the frozen world `ticks` ticks at once; return once `watcher` has what they sent."""
    await fast_forward(control, ticks)
    await watcher.sync()


async def _last_death(context: GroupContext, watcher: Bot, ticks: range) -> int | None:
    """Step the world once for each of `ticks`; the last of them on which a pig died, if any."""
    last = None
    died = _dead(_healths(watcher))
    for tick in ticks:
        await context.step()
        now = _dead(_healths(watcher))
        if now > died:
            last, died = tick, now
    return last


async def _while_off(context: GroupContext, watcher: Bot) -> None:
    """Let the crowd stand `OFF_TICKS` ticks; sample how many pigs are hurt."""
    await _run_on(context.control, watcher, OFF_TICKS)
    context.sample("cramming.hurt_when_off", _hurt(_healths(watcher)))


async def _while_on(context: GroupContext, watcher: Bot) -> None:
    """Turn cramming on and let the crowd stand `CRAMMING_TICKS` ticks; sample what it does.

    The samples are how many pigs are hurt after tick 1 and after tick 10, the last tick a pig
    died on, if one did, and how many pigs are alive at the end.
    """
    await context.control.run(f"gamerule {_CRAMMING_RULE} {_CRAMMING_LIMIT}")
    await context.step()
    context.sample("cramming.hurt_by_tick_1", _hurt(_healths(watcher)))
    await _run_on(context.control, watcher, _FIRST_TICKS - 1)
    context.sample("cramming.hurt_by_tick_10", _hurt(_healths(watcher)))
    last = await _last_death(context, watcher, range(_FIRST_TICKS + 1, CRAMMING_TICKS + 1))
    if last is not None:
        context.sample("cramming.last_death", last)
    healths = _healths(watcher)
    context.sample("cramming.alive", len(healths) - _dead(healths))


@group("entities/cramming", kind=GroupKind.STATISTICAL, runs=CRAMMING_RUNS)
async def cramming(context: GroupContext) -> None:
    """30 pigs stand in one block space with cramming off, then on; how many are hurt, and die.

    The play joins a watcher of its own (`GroupContext.player_name`), which is told about the
    pigs. The crowd stands `OFF_TICKS` ticks with `max_entity_cramming` 0, then the rule goes
    back to 24 and it stands `CRAMMING_TICKS` ticks more, counted from 1.
    """
    off: _Rule = (_CRAMMING_RULE, "0", str(_CRAMMING_LIMIT))
    async with _arena(context, context.player_name("crowd"), (off,)) as (watcher, _):
        for place in _grid(_CRAM_AT):
            await context.control.run(_summon(place))
        await _while_off(context, watcher)
        await _while_on(context, watcher)
