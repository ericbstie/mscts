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

The Bot joins where the server saved it (`pin_joins`), and the Group moves it and Control away
from every block it sets (docs/roles/player-actions.md, #300): a block set where a player stands
makes it crawl and choke on one Instance only. Each Bot is put back at the spawn when the Group
ends, so that it does not rejoin inside a block. Natural regeneration is off, so health stays what
the damage left it. Every setting is put back afterwards, because every Group is played on the same
two Instances. (Mobs do not spawn: the Fixture world has `spawn_mobs` off, ADR-0013, and no Group
turns it on.)
"""

import contextlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from mscts.bot import Bot
from mscts.compare import Mask
from mscts.group import Control, GroupContext, GroupKind, group
from mscts.groups._world import CONTROL_AT, fresh, join_at_spawn, normal, pin_joins
from mscts.net import ProtocolError
from mscts.spec import CONTROL_PLAYER

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

_RULES = (
    ("natural_health_regeneration", "false", "true"),
    ("random_tick_speed", "0", "3"),
)
"""The game rules a Group sets: the rule, the value it plays with and the value the Fixture world
has (vanilla's default). Not `spawn_mobs`: the Fixture has it off already (ADR-0013)."""

_HEAL = "effect give {bot} minecraft:instant_health 1 5 true"
"""Heals a Bot to full health, whatever the last case left it."""

type _Point = tuple[float, float, float]


@contextlib.asynccontextmanager
async def _environment(
    context: GroupContext, restore: tuple[str, ...]
) -> AsyncIterator[contextlib.AsyncExitStack]:
    """Set the join and game rules and move Control away; undo each on exit.

    `restore` are the commands that put back every block the Group sets. Yields the stack of
    undos, for what the body sets: they run first, then the block restores, then the rules. Each
    undo runs even if another fails, and after the body however it ended.
    """
    control: Control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        for rule, value, back in _RULES:
            undo.push_async_callback(control.run, f"gamerule {rule} {back}")
            await control.run(f"gamerule {rule} {value}")
        await control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
        for command in restore:
            undo.push_async_callback(control.run, command)
        yield undo


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
class _Site:
    """A place in a lane: the commands that build it and restore it, and where a Bot stands there.

    Attributes:
        lane: Its place along x.
        build: The commands that make the surface.
        restore: The commands that put the flat world back.
        lands_at: The y a player stands at there.
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


def _solid(lane: int, block: str, *, lands_at: float = -59.0) -> _Site:
    """A block on the grass."""
    return _Site(lane, (_block(lane, -60, block),), (_block(lane, -60, "minecraft:air"),), lands_at)


_STONE = _solid(0, "minecraft:stone")
_WATER = _Site(
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
_BED = _Site(
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


def _descent(landing: _Site, height: int) -> list[tuple[float, bool]]:
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


async def _fall(context: GroupContext, bot: Bot, landing: _Site, height: int) -> None:
    """Heal the Bot, put it `height` blocks above `landing`, and report its fall in a window."""
    start = landing.lands_at + height
    await context.control.run(_HEAL.format(bot=bot.name))
    await _tp(context, bot, _at(landing.lane, start))
    async with context.observe(*PACKETS):
        for y, on_ground in _descent(landing, height):
            await bot.move(*_at(landing.lane, y), on_ground=on_ground)
            await context.step_after(bot)


@group("player/fall", kind=GroupKind.TICK_EXACT, spec=normal)
async def fall(context: GroupContext) -> None:
    """A Bot falls 3, 4, 10 and 23 blocks onto stone, water, hay, slime and a bed.

    Then it falls 10 blocks onto stone with `fall_damage` off, and last 23 blocks onto stone,
    which kills it: the Bot respawns in a window of its own.
    """
    restore = (_KILL_ITEMS, *(c for landing in _LANDINGS for c in landing.restore))
    async with _environment(context, restore) as undo:
        bot = await join_at_spawn(context, undo, _FALLER)
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
# sent. A player ticks in real time, so each window must open before the next hit comes.

_SET_HEALTH = "minecraft:set_health"

_DAMAGE_TIMEOUT_S = 60.0
"""How long a window waits for a hit: drowning takes 320 ticks, 16 s at 20 ticks a second."""

_TICK_S = 0.05

_SLACK_TICKS = 2
"""How many ticks short of the time between two hits a window must open: the clock below starts
when the last window closed, a little after the hit."""

clock = time.monotonic
"""The clock that times the gap between a hit and the next window. Tests replace it."""


class _Hits:
    """The windows that end on a Bot's hits, and the time between them.

    A player ticks in real time, so a window that opens late lets the next hit through between
    two windows: its `set_health` is taken by the barrier before the window opens, and every
    window after it holds another health. The Reference would then differ from itself. So a window
    that opens later than a hit's period allows fails the Group instead (`ProtocolError`): on the
    Reference that is an `error`, never a Candidate's `mismatch`.
    """

    def __init__(self, context: GroupContext, bot: Bot) -> None:
        self._context = context
        self._bot = bot
        self._last_hit: float | None = None

    def check_gap(self, period_ticks: int) -> None:
        """Fail if the last hit is older than a hit `period_ticks` ticks apart allows.

        Raises:
            ProtocolError: The next hit may already have come, unseen.
        """
        if self._last_hit is None:
            return
        allowed_s = (period_ticks - _SLACK_TICKS) * _TICK_S
        waited_s = clock() - self._last_hit
        if waited_s > allowed_s:
            msg = (
                f"{self._bot.name} was {waited_s:.2f} s since its last hit when the next window "
                f"opened, but hits come {period_ticks} ticks apart: the next may have come "
                "between the windows, and the windows would hold another health from here on"
            )
            raise ProtocolError(msg)

    @contextlib.asynccontextmanager
    async def window(
        self, names: tuple[str, ...], *, period_ticks: int | None = None
    ) -> AsyncIterator[None]:
        """A window that runs the body, then waits for the Bot's next `set_health` and ends on it.

        With `period_ticks`, the time since the last hit is checked after the body (`check_gap`).
        """
        async with self._context.observe(*names, until=_SET_HEALTH, bot=self._bot):
            yield
            if period_ticks is not None:
                self.check_gap(period_ticks)
            await self._bot.expect(_SET_HEALTH, timeout_s=_DAMAGE_TIMEOUT_S)
        self._last_hit = clock()

    async def more(self, count: int, *, period_ticks: int) -> None:
        """Wait for `count` more hits, each in a window of its own."""
        for _ in range(count):
            async with self.window(HIT_PACKETS, period_ticks=period_ticks):
                pass


# `player/drowning`: a Bot stays under water until it drowns, a few times.

_DROWNER = "drowner"
_DROWNING_DAMAGE = "gamerule drowning_damage"
_HITS_AFTER = 3
_DROWNING_PERIOD = 20
"""Ticks between two drowning hits: the air is back at 0 and runs out again."""


@group("player/drowning", spec=normal)
async def drowning(context: GroupContext) -> None:
    """A Bot stays under water until it takes damage and for three hits after.

    Then `drowning_damage` is turned off, and the Bot stays under water for one more hit's time.
    """
    async with _environment(context, _WATER.restore) as undo:
        bot = await join_at_spawn(context, undo, _DROWNER)
        await context.freeze()
        for command in _WATER.build:
            await context.control.run(command)
        await fresh(context, bot)
        hits = _Hits(context, bot)
        async with hits.window(PACKETS):
            await _tp(context, bot, _at(_WATER.lane, -62.0))
        await hits.more(_HITS_AFTER, period_ticks=_DROWNING_PERIOD)
        undo.push_async_callback(context.control.run, f"{_DROWNING_DAMAGE} true")
        await context.control.run(f"{_DROWNING_DAMAGE} false")
        # The bubbles still come when the damage does not: the window ends a barrier after them.
        async with context.observe(*HIT_PACKETS):
            hits.check_gap(_DROWNING_PERIOD)
            await bot.expect("minecraft:entity_event", timeout_s=_DAMAGE_TIMEOUT_S)


# `player/suffocation`: a Bot inside a block of stone.

_SUFFOCATOR = "suffocator"
_STONE_COLUMN = _Site(
    0,
    (_block(0, -60, "minecraft:stone"), _block(0, -59, "minecraft:stone")),
    (_block(0, -60, "minecraft:air"), _block(0, -59, "minecraft:air")),
    lands_at=-60.0,
)
"""Two blocks of stone, so that the Bot's feet and its eyes are inside."""
_INVULNERABLE_TICKS = 10
"""Ticks between two hits of damage that comes every tick: the player is immune for 10."""


@group("player/suffocation", spec=normal)
async def suffocation(context: GroupContext) -> None:
    """A Bot is put inside a column of stone and takes damage, three hits in a row."""
    async with _environment(context, _STONE_COLUMN.restore) as undo:
        bot = await join_at_spawn(context, undo, _SUFFOCATOR)
        await context.freeze()
        for command in _STONE_COLUMN.build:
            await context.control.run(command)
        await fresh(context, bot)
        hits = _Hits(context, bot)
        async with hits.window(PACKETS):
            await _tp(context, bot, _at(_STONE_COLUMN.lane, _STONE_COLUMN.lands_at))
        await hits.more(2, period_ticks=_INVULNERABLE_TICKS)


# `player/void`: a Bot below the world.

_VOID_BOT = "voider"
_VOID_AT: _Point = (0.5, -130.0, 0.5)
"""Vanilla hurts a player below the lowest block minus 64 (`Entity.checkBelowWorld`): y -128."""

_DEATH = "minecraft:player_combat_kill"


@group("player/void", spec=normal)
async def void(context: GroupContext) -> None:
    """A Bot is put below the world, takes 4 points of damage a hit until it dies, and respawns."""
    async with _environment(context, ()) as undo:
        bot = await join_at_spawn(context, undo, _VOID_BOT)
        await context.freeze()
        await fresh(context, bot)
        async with context.observe(*PACKETS, until=_DEATH, bot=bot):
            await _tp(context, bot, _VOID_AT)
            await bot.expect(_DEATH, timeout_s=_DAMAGE_TIMEOUT_S)
        async with context.observe(*PACKETS):
            await bot.respawn()


# `player/fire`: a Bot in fire, in lava, out of it still burning, then in water.

_BURNER = "burner"
_LAVA = _Site(
    2,
    (_block(2, -62, "minecraft:lava"), _block(2, -61, "minecraft:lava")),
    (_block(2, -62, "minecraft:dirt"), _block(2, -61, "minecraft:grass_block")),
    lands_at=-61.0,
)
"""A pool of lava like the water's: 2 blocks deep and 1 wide, walled in by the world."""
_FIRE = _solid(3, "minecraft:fire", lands_at=-60.0)
_DRY_LANE = 5
"""A lane of bare grass: the Bot burns on there."""
_BURN_PERIOD = 20
"""Ticks between two burns of a player on fire (`Entity.baseTick`: every 20 ticks)."""

FIRE_MASKS = (
    Mask(
        "minecraft:sound",
        "pitch",
        "Vanilla draws it at random for the sounds a burning player is sent (26.3 javap): "
        "`Entity.lavaHurt` plays GENERIC_BURN at volume 0.4 with pitch 2.0 + nextFloat() * 0.4, "
        "and `playEntityOnFireExtinguishedSound` plays GENERIC_EXTINGUISH_FIRE at volume 0.7 with "
        "pitch 1.6 + (nextFloat() - nextFloat()) * 0.4. A pitch is fixed for other sounds, "
        "so only this Group masks it. Which sound plays, and at what volume, is still compared; "
        "how the pitch is distributed belongs to a statistical Group (#24).",
    ),
)
"""The pitch of the burn and extinguish sounds, which the sound seed does not cover."""


@group("player/fire", spec=normal, masks=FIRE_MASKS)
async def fire(context: GroupContext) -> None:
    """A Bot stands in fire; then, a fresh Bot steps into lava, out of it burning, and into water.

    The Bot is made fresh between fire and lava: a player is immune for 10 ticks after a hit, and
    a lava tick inside them hurts only by the excess, so the lava's full hit would come 10 ticks
    after the fire's, whichever window is open then. Each stop ends on the first hit after it. The
    last window ends a barrier after the water puts the fire out.
    """
    sites = (_WATER, _LAVA, _FIRE)
    async with _environment(context, tuple(c for site in sites for c in site.restore)) as undo:
        bot = await join_at_spawn(context, undo, _BURNER)
        await context.freeze()
        for command in (c for site in sites for c in site.build):
            await context.control.run(command)
        await fresh(context, bot)
        async with _Hits(context, bot).window(PACKETS):
            await _tp(context, bot, _at(_FIRE.lane, _FIRE.lands_at))
        await fresh(context, bot)
        hits = _Hits(context, bot)
        async with hits.window(PACKETS):
            await _tp(context, bot, _at(_LAVA.lane, _LAVA.lands_at))
        # The first tick out of lava must come at most 9 ticks after its last hit, or the burn
        # (remaining fire 300 at the first) is a full hit and a second lava hit ends the window.
        async with hits.window(PACKETS, period_ticks=_INVULNERABLE_TICKS):
            await _tp(context, bot, _at(_DRY_LANE, -60.0))
        async with context.observe(*PACKETS):
            await _tp(context, bot, _at(_WATER.lane, _WATER.lands_at))
            hits.check_gap(_BURN_PERIOD)


# `player/freezing`: a Bot in powder snow.

_FREEZER = "freezer"
_SNOW = _solid(4, "minecraft:powder_snow", lands_at=-60.0)
_FREEZING_PERIOD = 40
"""Ticks between two freezing hits: `tickCount % 40 == 0` in `LivingEntity.aiStep`."""

FREEZING_PACKETS = (*HIT_PACKETS, "minecraft:player_position")
"""What a window compares for freezing: the hits, and the Bot being put in the snow. Not the entity
data: vanilla hurts a frozen player when its `tickCount` is a multiple of 40, a count that started
at the respawn `fresh` makes, so the ticks that came before the first hit are timing."""


@group("player/freezing", spec=normal)
async def freezing(context: GroupContext) -> None:
    """A Bot is put in powder snow, without leather boots, and takes damage twice."""
    async with _environment(context, _SNOW.restore) as undo:
        bot = await join_at_spawn(context, undo, _FREEZER)
        await context.freeze()
        for command in _SNOW.build:
            await context.control.run(command)
        await fresh(context, bot)
        hits = _Hits(context, bot)
        async with hits.window(FREEZING_PACKETS):
            await _tp(context, bot, _at(_SNOW.lane, _SNOW.lands_at))
        async with hits.window(HIT_PACKETS, period_ticks=_FREEZING_PERIOD):
            pass
