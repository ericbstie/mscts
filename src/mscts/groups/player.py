"""Player Groups: how the environment hurts a player.

A survival player takes damage from a fall, from water over its head, from fire, from a block
around it, from the void and from powder snow. Each Group puts one Bot in such a place and
compares what the server sends it: the damage (`damage_event`), its health (`set_health`), its
entity data (air, fire and freeze), the sounds, and the server sending it back (`player_position`).

A player is not frozen by `tick freeze`: it ticks 20 times a second whatever the world does
(`TickRateManager.isEntityFrozen` is false for a `Player`, 26.3 javap). So what a tick of its own
does (breathing, burning, freezing) takes real time, and a Group that tests it ends its window
on the packet it waits for. What a move of the Bot does, the fall damage the server works out
when it reads a move that lands, is one packet pass, and a Group steps the world after each move
as the movement Groups do (`context.step`).

The Bot and Control join at the world spawn (`pin_joins`), and the Group moves both away from
every block it sets (docs/roles/player-actions.md, #300): a block set where a player stands makes
it crawl and choke on one Instance only. Natural regeneration is off, so health stays what the
damage left it, and mobs do not spawn. Every setting is put back afterwards, because every
Group is played on the same two Instances.
"""

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace

from mscts.bot import Bot
from mscts.compare import Mask
from mscts.group import Control, GroupContext, GroupKind, group
from mscts.groups._world import pin_joins
from mscts.spec import CONTROL_PLAYER, Difficulty, ServerSpec

PACKETS = (
    "minecraft:set_health",
    "minecraft:damage_event",
    "minecraft:hurt_animation",
    "minecraft:entity_event",
    "minecraft:set_entity_data",
    "minecraft:sound",
    "minecraft:player_position",
    "minecraft:player_combat_kill",
    "minecraft:respawn",
)
"""The packets a window compares: the damage, the hurt animation and entity events (vanilla sends
neither animation nor event for a hurt player, but drowning has one), the health, the entity data
(air, fire, freezing), the sounds, a correction of the player's place, a death and the respawn
after it."""

HIT_PACKETS = (
    "minecraft:damage_event",
    "minecraft:hurt_animation",
    "minecraft:entity_event",
    "minecraft:set_health",
    "minecraft:sound",
)
"""The packets a window compares for a hit after the first: what the hit itself sends. The entity
data is left out, because a window that opens after a hit starts a tick or two later on one
Instance than on another, and the entity data changes every tick (air, ticks frozen)."""

CONTROL_AT = "96.5 -60 96.5"
"""Where Control stands: 6 chunks from the spawn, clear of every block the Groups set (#300) and
out of the Bot's view, so that its entity is never sent to the Bot again when the Bot respawns:
vanilla sends it a tick or so later, which no window can place."""

_RULES = ("natural_health_regeneration false", "spawn_mobs false", "random_tick_speed 0")
"""The game rules a Group sets, and the commands that put each back to vanilla's default."""

_RULES_BACK = ("natural_health_regeneration true", "spawn_mobs true", "random_tick_speed 3")

_KILL_OTHERS = "kill @e[type=!minecraft:player]"
"""Removes the animals of the flat world's spawn area. A Bot that respawns is sent every entity in
its view again a tick or so later, which no window can place, and one of them may be hurt too."""

_HEAL = "effect give {bot} minecraft:instant_health 1 5 true"
"""Heals a Bot to full health, whatever the last case left it."""

type _Point = tuple[float, float, float]


def _normal(spec: ServerSpec) -> ServerSpec:
    """Play on normal difficulty: peaceful heals the player and stops most damage."""
    return replace(spec, difficulty=Difficulty.NORMAL)


@contextlib.asynccontextmanager
async def _environment(context: GroupContext, restore: tuple[str, ...]) -> AsyncIterator[None]:
    """Set the join and game rules and move Control away; undo each on exit.

    `restore` are the commands that put back every block the Group sets. Each undo runs even
    if another fails, and after the body however it ended.
    """
    control: Control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        for rule, back in zip(_RULES, _RULES_BACK, strict=True):
            undo.push_async_callback(control.run, f"gamerule {back}")
            await control.run(f"gamerule {rule}")
        await control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
        await control.run(_KILL_OTHERS)
        for command in restore:
            undo.push_async_callback(control.run, command)
        yield


async def _tp(context: GroupContext, bot: Bot, at: _Point) -> None:
    x, y, z = at
    await context.control.run(f"tp {bot.name} {x} {y} {z}")


# `player/fall`: a Bot reports a fall onto each surface, from each height.

_FALLER = "faller"

_LANE_Z = 2
"""The z of every landing lane; lane i is at x = 2 i + 1, one block wide, in chunk (0, 0)."""

_HEIGHTS = (3, 4, 10, 23)
"""How far the Bot falls: 3 blocks hurts no one, 4 hurts 1 point, 10 hurts 7, 23 hurts 20."""

_STEP = 8.0
"""The most a fall drops in one move: far below what the speed check allows, and few moves."""

_FALL_DAMAGE = "gamerule fall_damage"


@dataclass(frozen=True, slots=True)
class _Landing:
    """A lane's surface: the commands that build it and restore it, and where a Bot stands on it.

    Attributes:
        lane: Its place along x.
        build: The commands that make the surface.
        restore: The commands that put the flat world back.
        lands_at: The y a player stands at on this surface.
        approach: How far above `lands_at` the move before the landing is.
    """

    lane: int
    build: tuple[str, ...]
    restore: tuple[str, ...]
    lands_at: float
    approach: float = 1.0


def _lane_x(lane: int) -> int:
    return 2 * lane + 1


def _at(lane: int, y: float) -> _Point:
    return (_lane_x(lane) + 0.5, y, _LANE_Z + 0.5)


def _block(lane: int, y: int, block: str, *, dz: int = 0) -> str:
    return f"setblock {_lane_x(lane)} {y} {_LANE_Z + dz} {block}"


def _solid(lane: int, block: str, *, lands_at: float = -59.0) -> _Landing:
    """A block on the grass."""
    return _Landing(
        lane, (_block(lane, -60, block),), (_block(lane, -60, "minecraft:air"),), lands_at
    )


_STONE = _solid(0, "minecraft:stone")
_WATER = _Landing(
    1,
    (_block(1, -62, "minecraft:water"), _block(1, -61, "minecraft:water")),
    (_block(1, -62, "minecraft:dirt"), _block(1, -61, "minecraft:grass_block")),
    lands_at=-61.0,
    approach=0.5,
)
"""A pool in the ground, 2 blocks deep and 1 wide, walled in by the world: it cannot flow.

The Bot stands in it with its head out (the surface is at -60.11, its eyes 1.62 above its feet):
a player under water loses air in real time, which no stepped window can place.
"""
_HAY = _solid(2, "minecraft:hay_block")
_SLIME = _solid(3, "minecraft:slime_block")
_BED = _Landing(
    4,
    (
        _block(4, -60, "minecraft:red_bed[facing=south,part=head]", dz=1),
        _block(4, -60, "minecraft:red_bed[facing=south,part=foot]"),
    ),
    (_block(4, -60, "minecraft:air", dz=1), _block(4, -60, "minecraft:air")),
    lands_at=-59.4375,
)
"""A bed is 9/16 of a block high."""

_KILL_ITEMS = "kill @e[type=minecraft:item]"
"""Taking a bed away makes its other half drop as an item, which would stay in the Instance for
the next play: the Bot would pick it up, and drop it where it dies."""

_LANDINGS = (_STONE, _WATER, _HAY, _SLIME, _BED)


def _descent(landing: _Landing, height: int) -> list[tuple[float, bool]]:
    """The moves of a fall of `height` blocks onto `landing`: a y, and whether it is on the ground.

    The Bot drops at most `_STEP` a move, stops just above the surface (`approach`), and lands
    from there: a vanilla client sends the move that lands from just above. A move that goes
    from the air into water and lands in one is not a fall into water: vanilla learns that a
    player is in water on its tick (`wasTouchingWater`), after the move.
    """
    stops = landing.lands_at + landing.approach
    moves = []
    y = landing.lands_at + height - _STEP
    while y > stops:
        moves.append((y, False))
        y -= _STEP
    moves.append((stops, False))
    moves.append((landing.lands_at, True))
    return moves


async def _fall(context: GroupContext, bot: Bot, landing: _Landing, height: int) -> None:
    """Heal the Bot, put it `height` blocks above `landing`, and report its fall in a window."""
    start = landing.lands_at + height
    await context.control.run(_HEAL.format(bot=bot.name))
    await _tp(context, bot, _at(landing.lane, start))
    async with context.observe(*PACKETS):
        for y, on_ground in _descent(landing, height):
            await bot.move(*_at(landing.lane, y), on_ground=on_ground)
            await context.step(1)


@group("player/fall", kind=GroupKind.TICK_EXACT, spec=_normal)
async def fall(context: GroupContext) -> None:
    """A Bot falls 3, 4, 10 and 23 blocks onto stone, water, hay, slime and a bed.

    Then it falls 10 blocks onto stone with `fall_damage` off, and last 23 blocks onto stone,
    which kills it: the Bot respawns in a window of its own.
    """
    restore = (_KILL_ITEMS, *(c for landing in _LANDINGS for c in landing.restore))
    async with _environment(context, restore), contextlib.AsyncExitStack() as undo:
        bot = await context.bot(_FALLER)
        await bot.join()
        await _tp(context, bot, _at(_STONE.lane, -60.0))
        await context.freeze()
        for landing in _LANDINGS:
            for command in landing.build:
                await context.control.run(command)
        for landing in _LANDINGS:
            for height in _HEIGHTS[:-1] if landing is _STONE else _HEIGHTS:
                await _fall(context, bot, landing, height)
        undo.push_async_callback(context.control.run, f"{_FALL_DAMAGE} true")
        await context.control.run(f"{_FALL_DAMAGE} false")
        await _fall(context, bot, _STONE, 10)
        await context.control.run(f"{_FALL_DAMAGE} true")
        await _fall(context, bot, _STONE, _HEIGHTS[-1])
        async with context.observe(*PACKETS):
            await bot.respawn()


# Damage the player's own ticks do. The Bot is moved with `/tp` inside the window, which ends on
# the first `set_health` it receives after that: the damage, and everything the ticks before it
# sent. A player ticks in real time, so the number of ticks is what is compared, not a clock.

_SET_HEALTH = "minecraft:set_health"

_DAMAGE_TIMEOUT_S = 60.0
"""How long a window waits for a hit: drowning takes 320 ticks, 16 s at 20 ticks a second."""


async def _fresh(context: GroupContext, bot: Bot) -> None:
    """Kill the Bot and respawn it, so that it has full health, food and air and is not burning.

    The server saves a player when it leaves: its air, health and fire, and where it was.
    """
    await context.control.run(f"kill {bot.name}")
    await bot.respawn()


@contextlib.asynccontextmanager
async def _until_hurt(
    context: GroupContext, bot: Bot, names: tuple[str, ...]
) -> AsyncIterator[None]:
    """A window that runs the body, then waits for the Bot's next `set_health` and ends on it."""
    async with context.observe(*names, until=_SET_HEALTH, bot=bot):
        yield
        await bot.expect(_SET_HEALTH, timeout_s=_DAMAGE_TIMEOUT_S)


async def _more_hits(context: GroupContext, bot: Bot, count: int) -> None:
    """Wait for `count` more hits, each in a window of its own."""
    for _ in range(count):
        async with _until_hurt(context, bot, HIT_PACKETS):
            pass


# `player/drowning`: a Bot stays under water until it drowns, a few times.

_DROWNER = "drowner"
_DROWNING_DAMAGE = "gamerule drowning_damage"
_HITS_AFTER = 3


@group("player/drowning", spec=_normal)
async def drowning(context: GroupContext) -> None:
    """A Bot stays under water until it takes damage and for three hits after.

    Then `drowning_damage` is turned off, and the Bot stays under water for one more hit's time.
    """
    async with _environment(context, _WATER.restore), contextlib.AsyncExitStack() as undo:
        bot = await context.bot(_DROWNER)
        await bot.join()
        await context.freeze()
        for command in _WATER.build:
            await context.control.run(command)
        await _fresh(context, bot)
        async with _until_hurt(context, bot, PACKETS):
            await _tp(context, bot, _at(_WATER.lane, -62.0))
        await _more_hits(context, bot, _HITS_AFTER)
        undo.push_async_callback(context.control.run, f"{_DROWNING_DAMAGE} true")
        await context.control.run(f"{_DROWNING_DAMAGE} false")
        # The bubbles still come when the damage does not: the window ends a barrier after them.
        async with context.observe(*HIT_PACKETS):
            await bot.expect("minecraft:entity_event", timeout_s=_DAMAGE_TIMEOUT_S)


# `player/suffocation`: a Bot inside a block of stone.

_SUFFOCATOR = "suffocator"
_STONE_COLUMN = _Landing(
    0,
    (_block(0, -60, "minecraft:stone"), _block(0, -59, "minecraft:stone")),
    (_block(0, -60, "minecraft:air"), _block(0, -59, "minecraft:air")),
    lands_at=-60.0,
)
"""Two blocks of stone, so that the Bot's feet and its eyes are inside."""


@group("player/suffocation", spec=_normal)
async def suffocation(context: GroupContext) -> None:
    """A Bot is put inside a column of stone and takes damage, three hits in a row."""
    async with _environment(context, _STONE_COLUMN.restore):
        bot = await context.bot(_SUFFOCATOR)
        await bot.join()
        await context.freeze()
        for command in _STONE_COLUMN.build:
            await context.control.run(command)
        await _fresh(context, bot)
        async with _until_hurt(context, bot, PACKETS):
            await _tp(context, bot, _at(_STONE_COLUMN.lane, _STONE_COLUMN.lands_at))
        await _more_hits(context, bot, 2)


# `player/void`: a Bot below the world.

_VOID_BOT = "voider"
_VOID_AT: _Point = (0.5, -130.0, 0.5)
"""Vanilla hurts a player below the lowest block minus 64 (`Entity.checkBelowWorld`): y -128."""

_DEATH = "minecraft:player_combat_kill"


@group("player/void", spec=_normal)
async def void(context: GroupContext) -> None:
    """A Bot is put below the world, takes 4 points of damage a hit until it dies, and respawns."""
    async with _environment(context, ()):
        bot = await context.bot(_VOID_BOT)
        await bot.join()
        await context.freeze()
        await _fresh(context, bot)
        async with context.observe(*PACKETS, until=_DEATH, bot=bot):
            await _tp(context, bot, _VOID_AT)
            await bot.expect(_DEATH, timeout_s=_DAMAGE_TIMEOUT_S)
        async with context.observe(*PACKETS):
            await bot.respawn()


# `player/fire`: a Bot in fire, in lava, out of it still burning, then in water.

_BURNER = "burner"
_LAVA = _Landing(
    2,
    (_block(2, -62, "minecraft:lava"), _block(2, -61, "minecraft:lava")),
    (_block(2, -62, "minecraft:dirt"), _block(2, -61, "minecraft:grass_block")),
    lands_at=-61.0,
)
"""A pool of lava like the water's: 2 blocks deep and 1 wide, walled in by the world."""
_FIRE = _solid(3, "minecraft:fire", lands_at=-60.0)
_DRY_LANE = 5
"""A lane of bare grass: the Bot burns on there."""


FIRE_MASKS = (
    Mask(
        "minecraft:sound",
        "pitch",
        "Vanilla draws it at random (26.3 javap): `Entity.lavaHurt` plays GENERIC_BURN at volume "
        "0.4 with pitch 2.0 + nextFloat() * 0.4, and `playEntityOnFireExtinguishedSound` plays "
        "GENERIC_EXTINGUISH_FIRE at volume 0.7 with pitch 1.6 + (nextFloat() - nextFloat()) * "
        "0.4. Which sound plays, and at what volume, is still compared.",
    ),
)
"""The pitch of the burn and extinguish sounds, which the sound seed does not cover."""


@group("player/fire", spec=_normal, masks=FIRE_MASKS)
async def fire(context: GroupContext) -> None:
    """A Bot stands in fire, steps into lava, steps out of it burning, then into water.

    Each of the first three stops ends on the first hit after it, and fire gets one more. The
    last window ends a barrier after the water puts the fire out.
    """
    lanes = (_WATER, _LAVA, _FIRE)
    async with _environment(context, tuple(c for lane in lanes for c in lane.restore)):
        bot = await context.bot(_BURNER)
        await bot.join()
        await context.freeze()
        for command in (c for lane in lanes for c in lane.build):
            await context.control.run(command)
        await _fresh(context, bot)
        async with _until_hurt(context, bot, PACKETS):
            await _tp(context, bot, _at(_FIRE.lane, _FIRE.lands_at))
        await _more_hits(context, bot, 1)
        async with _until_hurt(context, bot, PACKETS):
            await _tp(context, bot, _at(_LAVA.lane, _LAVA.lands_at))
        async with _until_hurt(context, bot, PACKETS):
            await _tp(context, bot, _at(_DRY_LANE, -60.0))
        async with context.observe(*PACKETS):
            await _tp(context, bot, _at(_WATER.lane, _WATER.lands_at))


# `player/freezing`: a Bot in powder snow.

_FREEZER = "freezer"
_SNOW = _solid(4, "minecraft:powder_snow", lands_at=-60.0)

FREEZING_PACKETS = (*HIT_PACKETS, "minecraft:player_position")
"""What a window compares for freezing: the hits, and the Bot being put in the snow. Not the entity
data: vanilla hurts a frozen player when its `tickCount` is a multiple of 40, a count that
started when the player joined, so the ticks that came before the first hit differ."""


@group("player/freezing", spec=_normal)
async def freezing(context: GroupContext) -> None:
    """A Bot is put in powder snow, without leather boots, and takes damage twice."""
    async with _environment(context, _SNOW.restore):
        bot = await context.bot(_FREEZER)
        await bot.join()
        await context.freeze()
        for command in _SNOW.build:
            await context.control.run(command)
        await _fresh(context, bot)
        async with _until_hurt(context, bot, FREEZING_PACKETS):
            await _tp(context, bot, _at(_SNOW.lane, _SNOW.lands_at))
        await _more_hits(context, bot, 1)
