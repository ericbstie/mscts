"""Hopper Groups: when, and in what order, hoppers move items, as an open container shows it.

Each Group sets up the redstone arena (`redstone.arena`): the watcher at the spawn, random ticks
off, the world frozen, and its blocks set on the grass of chunk (0, 0). Then a Bot for each
container the Group watches stands beside it and opens it, all in one Observation window. The
window that steps the world compares what each open container sends: `container_set_slot`, and
`container_set_content` should a server send a whole menu again.

A hopper moves at most one item every 8 ticks, in the block entities' part of a tick, after the
players' part. So an open container sends the change in its player's next tick, which a frozen
world runs too, 50 ms later, before the step's barrier ends: an item a hopper moves on the step
of tick N shows on tick N (docs/research/2026-10-24-hoppers.md).

When a Group ends, each Bot closes its container, and the world steps 5 ticks, so that an open
chest's recheck of its openers, due 5 ticks after the last, has run before the chest goes: a
tick left due is saved with the chunk and would run in the next play.
"""

import contextlib
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from mscts.bot import Bot, Face
from mscts.group import GroupContext, GroupKind, group
from mscts.groups._world import fast_forward, join_at_spawn
from mscts.groups.redstone import At, arena, on_grass, stepped_window

_OPEN_PACKETS = (
    "minecraft:open_screen",
    "minecraft:container_set_content",
    "minecraft:container_set_slot",
)
"""What the window the Bots open their containers in compares: each menu and what is in it."""

_SLOT_PACKETS = ("minecraft:container_set_content", "minecraft:container_set_slot")
"""What a stepped window compares: what changes in each open container."""

_RECHECK_TICKS = 5
"""An open chest checks its openers again 5 ticks after the last check
(`ContainerOpenersCounter.scheduleRecheck`); one is still due once it closes."""


@dataclass(frozen=True, slots=True)
class _Opener:
    """A Bot that stands beside a container and opens it.

    Attributes:
        name: The Bot's name, e.g. `source`.
        stand: Where it stands, as `/tp` takes it: within reach of the container, and more
            than a block from any item a Group puts down, which it would pick up.
        container: The block it opens.
    """

    name: str
    stand: str
    container: tuple[int, int, int]


@contextlib.asynccontextmanager
async def _opened(context: GroupContext, openers: Sequence[_Opener]) -> AsyncIterator[None]:
    """Join a Bot for each of `openers`, stand it beside its container and open it, in one window.

    On the way out, each Bot closes its container, the world steps on until the chests' rechecks
    have run, and the Bots go back to the spawn.

    Raises:
        ValueError: The server opened no container for a Bot.
    """
    async with contextlib.AsyncExitStack() as undo:
        bots = []
        for opener in openers:
            bots.append(await join_at_spawn(context, undo, opener.name))
            await context.control.run(f"tp {opener.name} {opener.stand}")
        undo.push_async_callback(_close, context, bots)
        async with context.observe(*_OPEN_PACKETS):
            for bot, opener in zip(bots, openers, strict=True):
                await bot.place(*opener.container, Face.UP)
        shut = [bot.name for bot in bots if bot.inventory.window_id == 0]
        if shut:
            msg = (
                f"the container did not open for {', '.join(shut)}: the server sent no open_screen"
            )
            raise ValueError(msg)
        yield


async def _close(context: GroupContext, bots: Sequence[Bot]) -> None:
    """Close each Bot's container, then step the world on until the chests' rechecks have run.

    Each Bot waits until the server has closed its container: Control steps on another
    connection.
    """
    for bot in bots:
        await bot.close_container()
        await bot.sync()
    await fast_forward(context.control, _RECHECK_TICKS)


def _setblock(x: int, y: int, z: int, block: str) -> str:
    """The `/setblock` of `block` at x, y, z: above the grass, where `on_grass` does not reach."""
    return f"setblock {x} {y} {z} minecraft:{block}"


def _holding(block: str, *stacks: tuple[int, str, int]) -> str:
    """`block` with its container holding `stacks`, each a slot, an item and a count."""
    items = ",".join(
        f'{{Slot:{slot}b,id:"minecraft:{item}",count:{count}}}' for slot, item, count in stacks
    )
    return f"{block}{{Items:[{items}]}}"


# `redstone/hopper-transfer`: a chest at y -59, the source, over the upper hopper at x 4, which
# faces east into the lower hopper at x 5, which faces east into a chest at x 6, the target.

_TRANSFER_BUILD = (
    on_grass(5, 8, "hopper[facing=east]"),
    on_grass(4, 8, _holding("hopper[facing=east]", (1, "dirt", 1))),
    _setblock(4, -59, 8, _holding("chest", (0, "stone", 1), (2, "oak_log", 2))),
    on_grass(6, 8, "chest"),
)
"""The lower hopper is set first, so that it ticks first in each tick (`Level.tickBlockEntities`
ticks block entities in the order they were added). The upper hopper holds a dirt in its slot
1; the source a stone in slot 0 and 2 logs in slot 2, with slot 1 empty."""

_TRANSFER_OPENERS = (
    _Opener("source", "3.5 -60 6.5", (4, -59, 8)),
    _Opener("upper", "3.5 -60 10.5", (4, -60, 8)),
    _Opener("lower", "5.5 -60 10.5", (5, -60, 8)),
    _Opener("target", "7.5 -60 6.5", (6, -60, 8)),
)

_TRANSFER_TICKS = 32
"""A hopper pushes first, from its first slot that holds anything, then pulls one item from the
first slot of the container above that holds anything, into its own first slot that takes it;
then it waits 8 ticks (`HopperBlockEntity.tryMoveItems`). A hopper that another fills while it
is empty waits 8 ticks too, or 7 if it has ticked already in this tick, so the lower hopper
pushes 7 ticks after the upper one fills it (`tryMoveInItem`). The upper hopper pushes its dirt
and pulls the stone on tick 1, then pushes the stone and pulls a log on tick 9, and pushes and
pulls a log on tick 17, its slot 0 holding one log before and after, and pushes the last log on
tick 25. The lower hopper pushes each into the target on ticks 8, 16, 24 and 32: the dirt, the
stone, and two logs into one stack."""


@group("redstone/hopper-transfer", kind=GroupKind.TICK_EXACT)
async def hopper_transfer(context: GroupContext) -> None:
    """A hopper pulls from a chest and pushes into a second hopper, which fills a chest."""
    async with arena(context, _TRANSFER_BUILD), _opened(context, _TRANSFER_OPENERS):
        await stepped_window(context, (), _TRANSFER_TICKS, _SLOT_PACKETS)


# `redstone/hopper-full`: a hopper at x 4 that faces east into a chest at x 5.

_CHEST_SLOTS = 27

_FULL_CHEST = "5 -60 8"

_FULL_BUILD = (
    on_grass(4, 8, _holding("hopper[facing=east]", (0, "dirt", 3))),
    on_grass(5, 8, _holding("chest", *((slot, "stone", 64) for slot in range(_CHEST_SLOTS)))),
)
"""The hopper holds 3 dirt; the chest a stack of 64 stone in each slot."""

_FULL_OPENERS = (
    _Opener("hopper", "3.5 -60 10.5", (4, -60, 8)),
    _Opener("chest", "6.5 -60 10.5", (5, -60, 8)),
)


def _chest_slot(slot: int, stack: str) -> str:
    """Put `stack` in the chest's `slot`, with `/item`."""
    return f"item replace block {_FULL_CHEST} container.{slot} with minecraft:{stack}"


_FULL = (At(3, _chest_slot(13, "stone 63")), At(6, _chest_slot(20, "air")))
"""A hopper pushes nothing into a container whose every slot is full (`isFullContainer`), nor an
item that no slot takes: one stone short in slot 13 takes no dirt (`tryMoveInItem`). When nothing
moves, the hopper sets no cooldown and tries again on the next tick (`tryMoveItems`): it pushes
on tick 7, once slot 20 is empty, then on ticks 15 and 23."""

_FULL_TICKS = 23


@group("redstone/hopper-full", kind=GroupKind.TICK_EXACT)
async def hopper_full(context: GroupContext) -> None:
    """A hopper waits at a full chest, and pushes on the next tick once a slot takes its item."""
    async with arena(context, _FULL_BUILD), _opened(context, _FULL_OPENERS):
        await stepped_window(context, _FULL, _FULL_TICKS, _SLOT_PACKETS)
