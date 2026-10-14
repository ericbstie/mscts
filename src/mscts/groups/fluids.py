"""Fluid Groups: how water and lava spread, make new sources, and turn into stone, tick by tick.

A Bot called `watcher` stands at the spawn. Control lays a stone floor in chunk (0, 0), builds
what a Group needs on it, freezes the world and stops random ticks. Then, in one Observation
window, Control places each fluid with `/setblock` and steps the world a tick at a time, so the
window compares which blocks change on which tick: the fluid levels are block states.

Every case is placed a tick or more after the one before it, so that no two placements are sent
together. A placement made between two steps is due on the step its delay says: a frozen world's
game time stands still, and the block and fluid ticks run only on the ticks it steps
(docs/research/2026-10-03-tick-step.md). The window lasts until every source has had its last
scheduled tick. A source left with a tick due would run it in the next play, on a source placed
at the same block, and spread early (docs/research/2026-10-13-fluids.md).

When a Group ends, Control removes everything it built and placed, without updating the blocks
beside them, so that no tick is scheduled on the way out, and puts the grass back.
"""

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass

from mscts.group import GroupContext, GroupKind, group
from mscts.groups._world import CONTROL_AT, join_at_spawn, pin_joins
from mscts.spec import CONTROL_PLAYER

_WATCHER = "watcher"
"""The Bot whose packets the windows compare. It stands at the spawn, in chunk (0, 0)."""

_PACKETS = (
    "minecraft:block_update",
    "minecraft:section_blocks_update",
    "minecraft:level_event",
    "minecraft:sound",
)
"""What every window compares: the blocks a fluid changes, the lava's fizz, and any sound."""

_FLOOR = "fill 0 -61 0 15 -61 15 minecraft:stone"
"""The stone floor: the flat world's grass in chunk (0, 0), the one the watcher is sent first."""

_GRASS = "fill 0 -61 0 15 -61 15 minecraft:grass_block"
_CLEAR = "fill 0 -60 0 15 -59 15 minecraft:air"
"""Takes away every fluid and block a Group put on the floor."""

_CLEAR_STRICT = f"{_CLEAR} strict"
"""Clears without updating the blocks beside each one cleared (`FillCommand`: flag 816, then no
`updateNeighboursOnBlockSet`). A plain fill updates the shape of a lava or water source still
standing beside a block it clears, which schedules the source's tick; the chunk saves that tick
when it unloads and runs it after the next play's source is placed at the same block, so the
source spreads early (measured: 1 of 2 plays). The plain fill after it clears nothing on vanilla,
and clears the floor on a server without `strict`."""

_RANDOM_TICKS = "gamerule random_tick_speed"


@dataclass(frozen=True, slots=True)
class _At:
    """A command Control runs in the window once `tick` ticks have been stepped.

    Attributes:
        tick: How many ticks the window has stepped when the command runs; 0 is before the
            first step.
        command: The command, e.g. `setblock 8 -60 8 minecraft:water`.
    """

    tick: int
    command: str


@contextlib.asynccontextmanager
async def _arena(context: GroupContext, build: tuple[str, ...]) -> AsyncIterator[None]:
    """Join the watcher, lay the floor, run `build`, stop random ticks and freeze the world.

    On the way out, each undo runs even if another fails: the blocks go, then the grass comes
    back, then the rules.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        await control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
        await join_at_spawn(context, undo, _WATCHER)
        await control.run(f"{_RANDOM_TICKS} 0")
        undo.push_async_callback(control.run, f"{_RANDOM_TICKS} 3")
        undo.push_async_callback(control.run, _GRASS)
        undo.push_async_callback(control.run, _CLEAR)
        undo.push_async_callback(control.run, _CLEAR_STRICT)
        await control.run(_FLOOR)
        for command in build:
            await control.run(command)
        await context.freeze()
        yield


async def _observe(context: GroupContext, schedule: tuple[_At, ...], ticks: int) -> None:
    """In one window, step the world `ticks` ticks, running each command of `schedule` on time."""
    async with context.observe(*_PACKETS):
        for tick in range(ticks):
            for at in schedule:
                if at.tick == tick:
                    await context.control.run(at.command)
            await context.step(1)


# `fluids/water-spread` and `fluids/lava-spread`: a source in the middle of the open floor, and one
# that has a hole in the floor a few blocks east.

_HOLE = "setblock 15 -61 14 minecraft:air"
"""The hole: one block deep, in the floor at the chunk's east edge."""


def _spread(fluid: str, beside_hole: str) -> tuple[_At, ...]:
    """Place `fluid` in the middle of the floor, then a tick later at `beside_hole`."""
    return (
        _At(0, f"setblock 8 -60 8 minecraft:{fluid}"),
        _At(1, f"setblock {beside_hole} -60 14 minecraft:{fluid}"),
    )


_WATER_SPREAD = _spread("water", "12")
"""Water spreads a block every 5 ticks, a level less each time, up to 7 blocks
(`WaterFluid.getTickDelay`, `getDropOff`), and flows only toward a hole within 4 blocks
(`getSlopeFindDistance`): the second source is 3 blocks from the hole."""

_WATER_TICKS = 36
"""The middle source's last block changes on tick 35, 7 blocks out; one tick more."""


@group("fluids/water-spread", kind=GroupKind.TICK_EXACT)
async def water_spread(context: GroupContext) -> None:
    """Water spreads on an open floor, and flows toward a hole 3 blocks away."""
    async with _arena(context, (_HOLE,)):
        await _observe(context, _WATER_SPREAD, _WATER_TICKS)


_LAVA_SPREAD = _spread("lava", "13")
"""Lava spreads a block every 30 ticks, 2 levels less each time, up to 3 blocks
(`LavaFluid.getTickDelay`, `getDropOff`), and flows only toward a hole within 2 blocks
(`getSlopeFindDistance`): the second source is 2 blocks from the hole."""

_LAVA_TICKS = 92
"""The second source falls into the hole on tick 91; one tick more."""


@group("fluids/lava-spread", kind=GroupKind.TICK_EXACT)
async def lava_spread(context: GroupContext) -> None:
    """Lava spreads on an open floor, and flows toward a hole 2 blocks away."""
    async with _arena(context, (_HOLE,)):
        await _observe(context, _LAVA_SPREAD, _LAVA_TICKS)


# `fluids/sources`: two sources with a block between them, in a channel of stone (x 5 to 7), one
# channel each at z 2 (water, a new source), 6 (water, none), 10 (lava, a new source) and 14
# (lava, none).


def _channel(z: int) -> tuple[str, ...]:
    """Build a channel 3 blocks long at `z`, x 5 to 7, walled in stone."""
    return (
        f"fill 4 -60 {z - 1} 8 -60 {z + 1} minecraft:stone",
        f"fill 5 -60 {z} 7 -60 {z} minecraft:air",
    )


_WATER_RULE = "gamerule water_source_conversion"
_LAVA_RULE = "gamerule lava_source_conversion"

_SOURCES_BUILD = (*_channel(2), *_channel(6), *_channel(10), *_channel(14), f"{_LAVA_RULE} true")
"""The four channels, and the rule that lets lava make a source (vanilla's default is false)."""


def _pair(tick: int, z: int, fluid: str) -> tuple[_At, ...]:
    """Place a source of `fluid` at each end of the channel at `z`, a tick apart."""
    return (
        _At(tick, f"setblock 5 -60 {z} minecraft:{fluid}"),
        _At(tick + 1, f"setblock 7 -60 {z} minecraft:{fluid}"),
    )


_SOURCES = (
    *_pair(0, 10, "lava"),
    *_pair(2, 14, "lava"),
    *_pair(4, 2, "water"),
    _At(9, f"{_WATER_RULE} false"),
    *_pair(10, 6, "water"),
    _At(30, f"{_LAVA_RULE} false"),
)
"""The block between two sources becomes a source when the first spreads into it, if the
rule allows (`FlowingFluid.getNewLiquid`, `canConvertToSource`): water on tick 9 and lava on
tick 30. Each rule is turned off just after, before the second pair of its fluid spreads."""

_SOURCES_TICKS = 62
"""The lava between the last pair, and the pair, have their last scheduled tick on tick 62."""


@group("fluids/sources", kind=GroupKind.TICK_EXACT)
async def sources(context: GroupContext) -> None:
    """Two sources a block apart make a new one, with each source conversion rule on and off."""
    control = context.control
    async with contextlib.AsyncExitStack() as rules:
        rules.push_async_callback(control.run, f"{_WATER_RULE} true")
        rules.push_async_callback(control.run, f"{_LAVA_RULE} false")
        async with _arena(context, _SOURCES_BUILD):
            await _observe(context, _SOURCES, _SOURCES_TICKS)


# `fluids/interactions`, x 10 to 14: lava meets water four ways, each in stone walls.

_INTERACTIONS_BUILD = (
    # z 2: a lava source at x 11 and a water source at x 13, which flows onto it.
    "fill 10 -60 1 14 -60 3 minecraft:stone",
    "fill 11 -60 2 13 -60 2 minecraft:air",
    # z 6: a lava source at x 11, which flows toward a water source at x 13.
    "fill 10 -60 5 14 -60 7 minecraft:stone",
    "fill 11 -60 6 13 -60 6 minecraft:air",
    # z 10: water in a pit in the floor, and a lava source above it.
    "fill 11 -60 9 13 -60 11 minecraft:stone",
    "setblock 12 -60 10 minecraft:air",
    "setblock 12 -61 10 minecraft:air",
    # z 14: a lava source at x 11, which flows onto soul soil beside blue ice.
    "fill 10 -60 13 14 -60 15 minecraft:stone",
    "fill 11 -60 14 12 -60 14 minecraft:air",
    "setblock 13 -60 14 minecraft:blue_ice",
    "setblock 12 -61 14 minecraft:soul_soil",
)

_INTERACTIONS = (
    _At(0, "setblock 12 -61 10 minecraft:water"),
    _At(1, "setblock 12 -60 10 minecraft:lava"),
    _At(2, "setblock 11 -60 6 minecraft:lava"),
    _At(3, "setblock 11 -60 14 minecraft:lava"),
    _At(4, "setblock 11 -60 2 minecraft:lava"),
    _At(5, "setblock 13 -60 2 minecraft:water"),
    _At(28, "setblock 13 -60 6 minecraft:water"),
)
"""Lava over the water turns it to stone on tick 31; the flowing lava next to the water source
turns to cobblestone on tick 32, and over the soul soil to basalt on tick 33; the water flowing
next to the lava source turns it to obsidian on tick 10 (`LiquidBlock.shouldSpreadLiquid`,
`LavaFluid.spreadTo`). The water source of z 6 comes on tick 28, just before the lava reaches
it, so that it has not flowed toward the lava first."""

_INTERACTIONS_TICKS = 63
"""Each lava source runs its last scheduled tick 30 ticks after its neighbour changed: the last on
tick 63."""


@group("fluids/interactions", kind=GroupKind.TICK_EXACT)
async def interactions(context: GroupContext) -> None:
    """Lava and water meet and make stone, cobblestone, obsidian and basalt."""
    async with _arena(context, _INTERACTIONS_BUILD):
        await _observe(context, _INTERACTIONS, _INTERACTIONS_TICKS)
