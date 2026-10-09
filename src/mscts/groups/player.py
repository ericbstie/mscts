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
from mscts.group import Control, GroupContext, GroupKind, group
from mscts.groups._world import pin_joins
from mscts.spec import CONTROL_PLAYER, Difficulty, ServerSpec

PACKETS = (
    "minecraft:set_health",
    "minecraft:damage_event",
    "minecraft:set_entity_data",
    "minecraft:sound",
    "minecraft:player_position",
    "minecraft:player_combat_kill",
    "minecraft:respawn",
)
"""The packets a window compares: the damage, the health, the entity data (air, fire, freezing),
the sounds, a correction of the player's place, a death and the respawn after it."""

CONTROL_AT = "96.5 -60 96.5"
"""Where Control stands: 6 chunks from the spawn, clear of every block the Groups set (#300) and
out of the Bot's view, so that its entity is never sent to the Bot again when the Bot respawns:
vanilla sends it a tick or so later, which no window can place."""

_RULES = ("natural_health_regeneration false", "spawn_mobs false", "random_tick_speed 0")
"""The game rules a Group sets, and the commands that put each back to vanilla's default."""

_RULES_BACK = ("natural_health_regeneration true", "spawn_mobs true", "random_tick_speed 3")

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
