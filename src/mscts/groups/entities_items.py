"""Entity Groups: dropped items and experience orbs merging, despawning and being picked up.

Each Group joins one Bot at the world spawn and freezes the world, so that an item or orb changes
only on the ticks the Group steps. Control summons every item and orb with no motion, tagged, and
stands 6 chunks away, out of reach. When the Group ends, Control removes what it summoned (and
only that), takes away what the Bot picked up, puts the Bot back at the spawn and sets every rule
back, because every Group is played on the same two Instances.
"""

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass

from mscts.group import GroupContext, GroupKind, group
from mscts.groups._world import CONTROL_AT, join_at_spawn, pin_joins
from mscts.spec import CONTROL_PLAYER

_TAG = "mscts_items"
"""The tag every item and orb a Group summons carries, so that the Group removes only those."""

_STILL = f'Motion:[0.0d,0.0d,0.0d],NoGravity:1b,Tags:["{_TAG}"]'
"""What every summoned item and orb has: no motion and no gravity, so it stays where it is put,
and the Group's tag."""

type _Place = tuple[float, float, float]


def _at(place: _Place) -> str:
    """The coordinates of `place` for a command."""
    return " ".join(str(axis) for axis in place)


def _summon_item(place: _Place, stack: str, *more: str) -> str:
    """The command that summons an item of `stack` (`<id> <count>`) at `place`, still."""
    item_id, count = stack.split()
    fields = ",".join((f'Item:{{id:"{item_id}",count:{count}}}', _STILL, *more))
    return f"summon minecraft:item {_at(place)} {{{fields}}}"


@contextlib.asynccontextmanager
async def _arena(context: GroupContext, name: str) -> AsyncIterator[contextlib.AsyncExitStack]:
    """Join the Bot `name` empty, in survival, at the spawn; freeze the world.

    Yields the stack of undos, for what the body sets: they run first, each even if another
    fails. The summoned entities go before the Bot is emptied, since a player picks up an item
    with no pickup delay as soon as it has room. The server saves a player's items and
    experience with the player, so the Bot is emptied when the Group ends too.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        await control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
        await join_at_spawn(context, undo, name)
        undo.push_async_callback(control.run, f"xp set {name} 0 points")
        undo.push_async_callback(control.run, f"xp set {name} 0 levels")
        undo.push_async_callback(control.run, f"clear {name}")
        undo.push_async_callback(control.run, f"kill @e[tag={_TAG}]")
        await control.run(f"gamemode survival {name}")
        await control.run(f"clear {name}")
        await control.run(f"xp set {name} 0 levels")
        await control.run(f"xp set {name} 0 points")
        await context.freeze()
        yield undo


ITEM_PACKETS = (
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:remove_entities",
    "minecraft:take_item_entity",
    "minecraft:container_set_slot",
    "minecraft:set_player_inventory",
    "minecraft:set_experience",
    "minecraft:sound",
)
"""What every window compares: entities appearing, changing and going, a pickup, the Bot's slots
and experience, and sounds."""


# `entities/item-merge`

_WATCHER = "watcher"


@dataclass(frozen=True, slots=True)
class _Pair:
    """Two items side by side: their stacks, how far apart, and whether a glass pane is between.

    Attributes:
        first: The first item's stack, `<id> <count>`; it is summoned first.
        second: The second item's stack.
        dx: How far east of the first the second lies.
        dy: How far above the first the second floats.
        pane: Whether a glass pane stands between the two.
    """

    first: str
    second: str
    dx: float = 0.0
    dy: float = 0.0
    pane: bool = False


PAIRS = (
    _Pair("minecraft:stone 2", "minecraft:stone 3", dx=0.7),
    _Pair("minecraft:stone 2", "minecraft:stone 3", dx=0.8),
    _Pair("minecraft:stone 2", "minecraft:stone 3", dy=0.2),
    _Pair("minecraft:stone 2", "minecraft:stone 3", dy=0.3),
    _Pair("minecraft:stone 2", "minecraft:stone 3", dx=0.7, pane=True),
    _Pair("minecraft:stone 2", "minecraft:dirt 3", dx=0.3),
    _Pair("minecraft:stone 40", "minecraft:stone 30", dx=0.3),
    _Pair("minecraft:stone 32", "minecraft:stone 32", dx=0.3),
)
"""The pairs, west to east along z 6.5, 3 blocks apart and 6 blocks from the Bot, out of its
reach. Vanilla merges two items whose boxes, grown by 0.5 sideways, overlap: closer than 0.75
sideways and 0.25 upwards, through a wall too (`ItemEntity.mergeWithNeighbours`). It merges only
the same item with the same components, and only when the two make at most a stack
(`ItemEntity.areMergable`). The smaller goes into the larger; of two equal ones, the one that
ticks first, which is the one summoned first, goes into the other (`ItemEntity.tryToMerge`)."""

_ROW_Z = 6.5
_FLOOR = -60.0
_MERGE_TICKS = 40
"""An item looks for others to merge with on every 40th of its own ticks, while it does not move
to another block (`ItemEntity.tick`). A summoned item's first tick is its first."""


def _block_x(index: int) -> int:
    """The x of the block the pair `index` stands in."""
    return -11 + 3 * index


def _places(index: int, pair: _Pair) -> tuple[_Place, _Place]:
    """Where the two items of the pair `index` lie: the first 0.15 into its block."""
    x = round(_block_x(index) + 0.15, 2)
    first = (x, _FLOOR, _ROW_Z)
    second = (round(x + pair.dx, 2), round(_FLOOR + pair.dy, 2), _ROW_Z)
    return first, second


async def _lay(context: GroupContext, undo: contextlib.AsyncExitStack, index: int) -> None:
    """Summon the two items of the pair `index`, with its pane, which `undo` takes away."""
    control = context.control
    pair = PAIRS[index]
    if pair.pane:
        pane = f"{_block_x(index)} -60 6"
        await control.run(f"setblock {pane} minecraft:glass_pane")
        undo.push_async_callback(control.run, f"setblock {pane} minecraft:air")
    first, second = _places(index, pair)
    await control.run(_summon_item(first, pair.first))
    await control.run(_summon_item(second, pair.second))


@group("entities/item-merge", kind=GroupKind.TICK_EXACT)
async def item_merge(context: GroupContext) -> None:
    """Pairs of items lie side by side, near and far, and the world steps until each merges.

    The pairs are laid a tick apart, so that each merges on a tick of its own: vanilla sends
    the entity data that changed in a tick in an order that follows the entity ids (#320).
    """
    async with _arena(context, _WATCHER) as undo:
        for index in range(len(PAIRS)):
            if index:
                await context.step(1)
            await _lay(context, undo, index)
        async with context.observe(*ITEM_PACKETS):
            await context.step(_MERGE_TICKS + 1)
