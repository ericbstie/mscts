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
    have run, and the Bots go back to the spawn. A container that does not open is a difference
    the windows show, not an error: the Group plays on, and that Bot is sent no slot.
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


# `redstone/hopper-transfer`: three lines along z 8, 12 and 14, each an upper hopper at x 4
# that faces east into a lower hopper at x 5, which faces east into a chest at x 6, the target.
# On the first line a chest at y -59, the source, stands on the upper hopper.

_TRANSFER_BUILD = (
    on_grass(5, 8, "hopper[facing=east]"),
    on_grass(4, 8, _holding("hopper[facing=east]", (1, "dirt", 1), (3, "sand", 2))),
    _setblock(4, -59, 8, _holding("chest", (0, "stone", 1), (2, "oak_log", 2))),
    on_grass(6, 8, "chest"),
    on_grass(4, 12, _holding("hopper[facing=east]", (0, "dirt", 1))),
    on_grass(5, 12, "hopper[facing=east]"),
    on_grass(6, 12, "chest"),
    on_grass(5, 14, _holding("hopper[facing=east]", (0, "cobblestone", 2))),
    on_grass(4, 14, _holding("hopper[facing=east]", (0, "dirt", 1))),
    on_grass(6, 14, "chest"),
)
"""Block entities tick in the order they were added (`Level.tickBlockEntities`). On the first
line the lower hopper is set first, so that it ticks first in each tick. Its upper hopper holds a
dirt in slot 1 and 2 sand in slot 3; the source a stone in slot 0 and 2 logs in slot 2, with
slot 1 empty. On the second line the upper hopper, holding a dirt, is set first. On the third the
lower hopper is set first, holding 2 cobblestone, and its upper hopper holds a dirt."""

_TRANSFER_OPENERS = (
    _Opener("source", "3.5 -60 6.5", (4, -59, 8)),
    _Opener("upper", "3.5 -60 10.5", (4, -60, 8)),
    _Opener("lower", "5.5 -60 10.5", (5, -60, 8)),
    _Opener("target", "7.5 -60 6.5", (6, -60, 8)),
    _Opener("upper_first", "7.5 -60 12.5", (6, -60, 12)),
    _Opener("lower_holds", "7.5 -60 14.5", (6, -60, 14)),
)
"""On the second and third lines, only the target is open: its slots show when the lower hopper
pushed."""

_TRANSFER_TICKS = 48
"""A hopper pushes first, from its first slot that holds anything, then pulls one item from the
first slot of the container above that holds anything, into its own first slot that takes it;
then it waits 8 ticks (`HopperBlockEntity.tryMoveItems`). A hopper that another fills while it
is empty waits 8 ticks too, or 7 if it has ticked already in this tick, so the lower hopper
pushes 7 ticks after the upper one fills it (`tryMoveInItem`). The upper hopper pushes its dirt
and pulls the stone on tick 1, then pushes the stone and pulls a log on tick 9, and pushes and
pulls a log on tick 17, its slot 0 holding one log before and after. It pushes the last log on
tick 25, while its sand waits in slot 3, then a sand on ticks 33 and 41. The lower hopper pushes
each into the target on ticks 8, 16, 24, 32, 40 and 48: the dirt, the stone, two logs into one
stack and two sand into another.

On the second line the upper hopper ticks first, so the lower one has not ticked yet when it is
filled on tick 1: it waits 8 ticks and pushes the dirt on tick 8, again 7 ticks after it arrived.
On the third line the lower hopper pushes a cobblestone on tick 1, then the upper one fills it
while it holds the other, which sets no cooldown: it pushes the second cobblestone on tick 9 and
the dirt on tick 17."""


@group("redstone/hopper-transfer", kind=GroupKind.TICK_EXACT)
async def hopper_transfer(context: GroupContext) -> None:
    """A hopper pulls from a chest and pushes into a second hopper, which fills a chest.

    Two more lines of two hoppers each fill a chest: one whose upper hopper ticks first, and one
    whose lower hopper holds items when the upper one fills it.
    """
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

_HOPPER_THEN_CHEST = (
    _Opener("hopper", "3.5 -60 10.5", (4, -60, 8)),
    _Opener("chest", "6.5 -60 10.5", (5, -60, 8)),
)
"""The Bots that open the hopper at x 4 and the chest at x 5 it faces: in `redstone/hopper-full`
and `redstone/hopper-lock`."""


def _chest_slot(slot: int, stack: str) -> str:
    """Put `stack` in the chest's `slot`, with `/item`."""
    return f"item replace block {_FULL_CHEST} container.{slot} with minecraft:{stack}"


_FULL = (At(3, _chest_slot(13, "stone 63")), At(11, _chest_slot(20, "air")))
"""A hopper pushes nothing into a container whose every slot is full (`isFullContainer`), nor an
item that no slot takes: one stone short in slot 13 takes no dirt (`tryMoveInItem`). When nothing
moves, the hopper sets no cooldown and tries again on the next tick (`tryMoveItems`): it pushes
on tick 12, once slot 20 is empty, then on ticks 20 and 28. Slot 20 empties after tick 11, which
no number from 2 to 8 divides, so a hopper that tries again every 2 to 8 ticks from tick 1
pushes later."""

_FULL_TICKS = 28


@group("redstone/hopper-full", kind=GroupKind.TICK_EXACT)
async def hopper_full(context: GroupContext) -> None:
    """A hopper waits at a full chest, and pushes on the next tick once a slot takes its item."""
    async with arena(context, _FULL_BUILD), _opened(context, _HOPPER_THEN_CHEST):
        await stepped_window(context, _FULL, _FULL_TICKS, _SLOT_PACKETS)


# `redstone/hopper-pickup`: three hoppers facing down along z 4, at x 3, 7 and 11. Nothing is
# above the first; stone is above the second, and a bottom slab above the third.

_PICKUP_BUILD = (
    on_grass(3, 4, "hopper"),
    on_grass(7, 4, "hopper"),
    _setblock(7, -59, 4, "stone"),
    on_grass(11, 4, "hopper"),
    _setblock(11, -59, 4, "smooth_stone_slab[type=bottom]"),
)

_PICKUP_OPENERS = (
    _Opener("bare", "3.5 -60 7.5", (3, -60, 4)),
    _Opener("covered", "7.5 -60 7.5", (7, -60, 4)),
    _Opener("slabbed", "11.5 -60 7.5", (11, -60, 4)),
)
"""Each Bot stands 3 blocks from the items, out of the reach a player picks items up in."""


def _summon(at: str, item: str, count: int) -> str:
    """Summon `count` of `item` lying at `at`, still.

    It has no gravity, since the world's steps run entities too, and faces south: vanilla turns
    a new item entity at random (`ItemEntity`'s constructor), unless the summon says how.
    """
    stack = f'Item:{{id:"minecraft:{item}",count:{count}}}'
    return f"summon minecraft:item {at} {{{stack},NoGravity:1b,Rotation:[0f,0f]}}"


_IN_COVERED_BOWL = "7.5 -59.3 4.5"
"""In the covered hopper's bowl, below the stone: within the box it takes items from, which starts
at 11/16 of its block, y -59.3125."""

_PICKUP = (
    At(0, _summon("3.5 -59 4.5", "stone", 3)),
    At(0, _summon(_IN_COVERED_BOWL, "oak_log", 1)),
    At(0, _summon("11.5 -58.5 4.5", "stone", 1)),
    At(2, _summon("3.5 -59 4.5", "dirt", 2)),
    At(2, _summon(_IN_COVERED_BOWL, "dirt", 1)),
)
"""In its own tick, a hopper takes an item entity whose box meets the box from 11/16 of its block
up to 2 blocks above its base (`Hopper.SUCK_AABB`), unless a full block is above it, and then
waits 8 ticks (`HopperBlockEntity.suckInItems`). The first hopper takes the whole stack of stone
on tick 1, and the dirt that comes on tick 2 on tick 9. The third takes the stone on its slab on
tick 1.

An item in a hopper's bowl is also taken in the item's own tick, which comes before the hoppers'
in a tick, whenever the hopper is off its wait, full block or not
(`HopperBlockEntity.entityInside`). So the second hopper takes the log in its bowl on tick 1.
Its wait ends in its own tick on tick 8, which takes nothing through the stone and sets no wait,
so the dirt in its bowl goes on tick 9."""

_PICKUP_PACKETS = (
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:remove_entities",
    *_SLOT_PACKETS,
)
"""What the pickup window compares: the items that appear, and go, and the hoppers' slots."""

_PICKUP_TICKS = 9

_KILL_ITEMS = "kill @e[type=minecraft:item]"
"""Takes away any item a hopper left, so that the next play has none."""


@group("redstone/hopper-pickup", kind=GroupKind.TICK_EXACT)
async def hopper_pickup(context: GroupContext) -> None:
    """Hoppers take the items above them; under a full block, only the items in their bowl."""
    async with arena(context, _PICKUP_BUILD), _opened(context, _PICKUP_OPENERS):
        try:
            await stepped_window(context, _PICKUP, _PICKUP_TICKS, _PICKUP_PACKETS)
        finally:
            await context.control.run(_KILL_ITEMS)


# `redstone/hopper-lock`: the hopper and the chest of `redstone/hopper-full`, the chest empty,
# and a redstone block that Control places north of the hopper, at z 7, and takes away.

_LOCK_BUILD = (
    on_grass(4, 8, _holding("hopper[facing=east]", (0, "dirt", 3))),
    on_grass(5, 8, "chest"),
)


def _lock(tick: int) -> At:
    """Power the hopper on `tick`: a redstone block beside it."""
    return At(tick, on_grass(4, 7, "redstone_block"))


def _unlock(tick: int) -> At:
    """Take the redstone block beside the hopper away on `tick`."""
    return At(tick, on_grass(4, 7, "air"))


_LOCK = (_lock(0), _unlock(1), _lock(4), _unlock(7), _lock(16), _unlock(18))
"""A powered hopper is locked at once, and unlocked once the power goes
(`HopperBlock.checkPoweredState`). A locked hopper moves nothing and sets no cooldown, but its
cooldown still counts down (`HopperBlockEntity.pushItemsTick`). Locked from the start, the hopper
pushes on tick 2, once unlocked. A lock from tick 4 to 7 falls inside its cooldown, so it pushes
again on tick 10. The next push, due on tick 18, waits for the lock from tick 16 to 18 to go:
tick 19. Each lock that holds a push back goes right after the hopper's first try that it
stopped, so a hopper that waits 2 ticks or more to try again pushes later."""

_LOCK_PACKETS = (
    "minecraft:block_update",
    "minecraft:section_blocks_update",
    *_SLOT_PACKETS,
)
"""What the lock window compares: the redstone block and the hopper's `enabled`, and the slots."""

_LOCK_TICKS = 19


@group("redstone/hopper-lock", kind=GroupKind.TICK_EXACT)
async def hopper_lock(context: GroupContext) -> None:
    """A powered hopper moves nothing while its cooldown still counts down."""
    async with arena(context, _LOCK_BUILD), _opened(context, _HOPPER_THEN_CHEST):
        await stepped_window(context, _LOCK, _LOCK_TICKS, _LOCK_PACKETS)
