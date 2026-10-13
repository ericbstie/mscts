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


# `fluids/water-spread`: a source in the middle of the open floor, and one that has a hole in the
# floor a few blocks east.

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
