"""Redstone Groups: when repeaters, comparators, torches, observers and dust switch, tick by tick.

A Bot called `watcher` stands at the spawn. Control stops random ticks, freezes the world and
builds a Group's circuits with `/setblock` on the grass of chunk (0, 0), the one the watcher is
sent first. Then, in an Observation window, Control places or removes the redstone blocks that
feed the circuits and steps the world a tick at a time, so the window compares which blocks change
on which tick: whether a repeater, a comparator or an observer is powered, whether a torch is lit
and how strong each dust is are block states.

A frozen world's game time stands still, and its block ticks run only on the ticks it steps
(docs/research/2026-10-03-tick-step.md), so a component that a command changes between two steps
switches on the step its delay says. Every window ends with no tick due, since a tick left due is
saved with the chunk and would run in the next play (docs/research/2026-10-13-fluids.md). Facts:
docs/research/2026-10-17-redstone.md.

When a Group ends, Control removes everything it built without updating the blocks beside them,
so that no tick is scheduled on the way out.
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
    "minecraft:block_event",
    "minecraft:level_event",
    "minecraft:sound",
)
"""What every window compares: the blocks that change, a piston's action, a torch burning out,
and any sound."""

_CLEAR = "fill 1 -60 1 15 -57 15 minecraft:air"
"""Takes away every block a Group built or placed, on the grass of chunk (0, 0)."""

_CLEAR_STRICT = f"{_CLEAR} strict"
"""Clears without updating the blocks beside each one cleared (`FillCommand`: flag 816, then no
`updateNeighboursOnBlockSet`). A plain fill would update a repeater or a torch beside a block it
clears, which schedules its tick; the chunk saves that tick and runs it in the next play. The
plain fill after it clears nothing on vanilla, and clears the circuits on a server without
`strict`."""

_RANDOM_TICKS = "gamerule random_tick_speed"


@dataclass(frozen=True, slots=True)
class _At:
    """A command Control runs in the window once `tick` ticks have been stepped.

    Attributes:
        tick: How many ticks the window has stepped when the command runs; 0 is before the
            first step.
        command: The command, e.g. `setblock 2 -60 2 minecraft:redstone_block`.
    """

    tick: int
    command: str


@contextlib.asynccontextmanager
async def _arena(context: GroupContext, build: tuple[str, ...]) -> AsyncIterator[None]:
    """Join the watcher, stop random ticks, freeze the world, then run `build`.

    The world is frozen before the circuits are built, so that any tick a block schedules as it
    is placed comes due on a step, not on a running tick. On the way out, each undo runs even if
    another fails: the blocks go, then the rules.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        await control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
        await join_at_spawn(context, undo, _WATCHER)
        await control.run(f"{_RANDOM_TICKS} 0")
        undo.push_async_callback(control.run, f"{_RANDOM_TICKS} 3")
        undo.push_async_callback(control.run, _CLEAR)
        undo.push_async_callback(control.run, _CLEAR_STRICT)
        await context.freeze()
        for command in build:
            await control.run(command)
        yield


async def _observe(context: GroupContext, schedule: tuple[_At, ...], ticks: int) -> None:
    """In one window, step the world `ticks` ticks, running each command of `schedule` on time."""
    async with context.observe(*_PACKETS):
        for tick in range(ticks):
            for at in schedule:
                if at.tick == tick:
                    await context.control.run(at.command)
            await context.step(1)


def _set(x: int, z: int, block: str) -> str:
    """The `/setblock` of `block` at x, -60, z: on the grass."""
    return f"setblock {x} -60 {z} minecraft:{block}"


# `redstone/repeater`: a row of cases along x 2 to 3, each a repeater at x 3 facing west, so that
# its input is the block at x 2, where Control places and removes a redstone block.

_DELAYS = (1, 2, 3, 4)
"""The delay of the repeater at z 2, 4, 6 and 8: the redstone ticks it waits."""

_REPEATER_BUILD = (
    *(_set(3, 2 * delay, f"repeater[facing=west,delay={delay}]") for delay in _DELAYS),
    _set(3, 12, "redstone_block"),
    _set(3, 11, "repeater[facing=south,powered=true]"),
    _set(3, 10, "repeater[facing=west,locked=true]"),
    _set(3, 14, "repeater[facing=west,delay=4]"),
)
"""The four delays; at z 10 a repeater locked by a powered one at its side (z 11, fed by a
redstone block at z 12); at z 14 a repeater with a delay of 4, which is fed a 1-tick pulse."""

_REPEATER = (
    *(_At(0, _set(2, 2 * delay, "redstone_block")) for delay in _DELAYS),
    _At(0, _set(2, 10, "redstone_block")),
    _At(0, _set(2, 14, "redstone_block")),
    _At(1, _set(2, 14, "air")),
    *(_At(10, _set(2, 2 * delay, "air")) for delay in _DELAYS),
    _At(10, _set(3, 12, "air")),
    _At(16, _set(2, 10, "air")),
)
"""A repeater switches its delay times 2 ticks after its input does (`RepeaterBlock.getDelay`):
the four on ticks 2, 4, 6 and 8, and off on 12, 14, 16 and 18. The locked one ignores its input
(`DiodeBlock.checkTickOnNeighbor` returns while `isLocked`) until the repeater at its side goes
off on tick 12, then switches 2 ticks later, on 14, and off on 18. The pulse of 1 tick comes out
8 ticks long, on ticks 8 to 16 (`DiodeBlock.tick` schedules the next switch when its input is
already off)."""

_REPEATER_TICKS = 19
"""The last repeaters switch off on tick 18; one tick more."""


@group("redstone/repeater", kind=GroupKind.TICK_EXACT)
async def repeater(context: GroupContext) -> None:
    """Repeaters of each delay, a locked one, and one fed a 1-tick pulse, switch on time."""
    async with _arena(context, _REPEATER_BUILD):
        await _observe(context, _REPEATER, _REPEATER_TICKS)
