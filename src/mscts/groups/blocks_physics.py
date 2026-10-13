"""Blocks Groups: falling blocks, and blocks that lose what holds them up, tick by tick.

A Bot called `watcher` joins at the world spawn and watches. Control builds every case of a
Group with `/setblock` in a frozen world, then steps the world until the ticks the blocks
scheduled when they were placed have run. In each window Control removes one block with
`setblock ... air`, and steps the world a fixed number of ticks, one at a time, until nothing
moves. The world stays frozen in between, so a case changes only in its own window. Control and
the watcher are the only players: Control stands 6 chunks away, and the watcher is sent every
block these Groups change, which are all in chunk (0, 0) (docs/guide/writing-a-group.md).

When a Group ends, Control clears its blocks, kills the items they dropped, puts the watcher back
at the spawn and sets every rule back, because every Group is played on the same two Instances.
Facts: docs/research/2026-10-13-block-physics.md.
"""

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass

from mscts.compare import Mask
from mscts.group import GroupContext, GroupKind, group
from mscts.groups._world import CONTROL_AT, join_at_spawn, pin_joins
from mscts.groups.blocks import DROP_MASKS
from mscts.spec import CONTROL_PLAYER

WATCHER = "watcher"
"""The Bot that is told what falls and what breaks."""

SETTLE_TICKS = 5
"""How many ticks the world steps after Control builds, before the first window: a falling block
schedules a tick 2 ticks after it is placed (`FallingBlock.onPlace`), and water 5. While every
block still stands on another, those ticks change nothing."""

_KILL_ITEMS = "kill @e[type=minecraft:item]"


@dataclass(frozen=True, slots=True)
class _Case:
    """One window: what Control builds before the first window, and removes and steps in this one.

    `layout` is the blocks Control sets, bottom first, `release` the block it removes in the
    window, and `ticks` how many ticks the window steps. `drops` is whether the case ends with
    an item on the ground, which Control kills after the window: an item moves at random, so a
    window ends on the tick it appears.
    """

    layout: tuple[str, ...]
    release: str
    ticks: int
    drops: bool = False


@contextlib.asynccontextmanager
async def _arena(context: GroupContext, clear: str) -> AsyncIterator[None]:
    """Join the watcher at the spawn and freeze the world; on the way out, `clear` and set back.

    Each undo runs even if another fails. The blocks are cleared before the items are killed: a
    block cleared can break another, which drops an item.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        await control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
        await join_at_spawn(context, undo, WATCHER)
        undo.push_async_callback(control.run, "gamerule random_tick_speed 3")
        await control.run("gamerule random_tick_speed 0")
        undo.push_async_callback(control.run, _KILL_ITEMS)
        undo.push_async_callback(control.run, clear)
        await context.freeze()
        yield


async def _build(context: GroupContext, cases: tuple[_Case, ...]) -> None:
    """Set every case's blocks, then step the world until what they scheduled has run."""
    for case in cases:
        for command in case.layout:
            await context.control.run(command)
    await context.step(SETTLE_TICKS)


async def _release(context: GroupContext, case: _Case, packets: tuple[str, ...]) -> None:
    """Remove the case's block and step its ticks, in a window; then kill what it dropped."""
    async with context.observe(*packets):
        await context.control.run(f"setblock {case.release} minecraft:air")
        await context.step(case.ticks)
    if case.drops:
        await context.control.run(_KILL_ITEMS)


async def _play(
    context: GroupContext, cases: tuple[_Case, ...], clear: str, packets: tuple[str, ...]
) -> None:
    """Build every case, then release each in a window of its own that compares `packets`."""
    async with _arena(context, clear):
        await _build(context, cases)
        for case in cases:
            await _release(context, case, packets)


# `blocks/gravity`: a row of cases along z 8, 3 blocks apart, on the flat world's grass (y -61).

GRAVITY_PACKETS = (
    "minecraft:block_update",
    "minecraft:section_blocks_update",
    "minecraft:add_transient_block",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:remove_entities",
    "minecraft:level_event",
    "minecraft:sound",
)
"""What a gravity window compares: the blocks, the falling block entity as it appears and goes,
the block it lands as (`add_transient_block` too), the item it breaks into, and the landing's
sound and event.

It leaves out how the falling block moves. Vanilla sends that every so many ticks of the
entity's tracker (`ServerEntity.sendChanges`), which `ChunkMap.tick` runs in frozen ticks too,
so which step it comes in depends on how long each step takes (26.3 javap; 2 plays of 20 did not
match on it)."""

_COLUMN = ("minecraft:sand", "minecraft:gravel", "minecraft:red_sand") * 2

GRAVITY_CASES = (
    _Case(
        layout=(
            "setblock 2 -60 8 minecraft:stone",
            *(f"setblock 2 {-59 + up} 8 {block}" for up, block in enumerate(_COLUMN)),
        ),
        release="2 -60 8",
        ticks=18,
    ),
    _Case(
        layout=(
            "setblock 4 -60 8 minecraft:stone",
            "setblock 6 -60 8 minecraft:stone",
            "setblock 5 -60 7 minecraft:stone",
            "setblock 5 -60 9 minecraft:stone",
            "setblock 5 -60 8 minecraft:water",
            "setblock 5 -59 8 minecraft:stone",
            "setblock 5 -58 8 minecraft:white_concrete_powder",
        ),
        release="5 -59 8",
        ticks=8,
    ),
    _Case(
        layout=(
            "setblock 8 -60 8 minecraft:stone",
            "setblock 8 -59 8 minecraft:anvil[facing=north]",
        ),
        release="8 -60 8",
        ticks=8,
    ),
    _Case(
        layout=(
            "setblock 11 -60 8 minecraft:torch",
            "setblock 11 -59 8 minecraft:stone",
            "setblock 11 -58 8 minecraft:sand",
        ),
        release="11 -59 8",
        ticks=11,
        drops=True,
    ),
    _Case(
        layout=(
            "setblock 14 -60 8 minecraft:smooth_stone_slab[type=bottom]",
            "setblock 14 -59 8 minecraft:stone",
            "setblock 14 -58 8 minecraft:sand",
        ),
        release="14 -59 8",
        ticks=10,
        drops=True,
    ),
)
"""A column of sand, gravel and red sand 6 high; white concrete powder over water, in a basin of
stone; an anvil; sand over a torch, and over a bottom slab, each of which it breaks into an item.

A block falls on the second step after the block under it goes (the delay of 2), the one above
it two steps later, and after a fall of one block it lands on the 8th step (vanilla 26.3,
measured): the column's last block lands on the 18th. Sand falls 2 blocks onto the torch and
breaks on the 11th step, and 1.5 onto the slab, on the 10th. Each window ends on that step.

The anvil falls one block. One that falls further lands chipped at random: `FallingBlockEntity
.causeFallDamage` draws `random.nextFloat() < 0.05 + 0.05 * ceil(fallDistance - 1)` once the
fall would hurt, which a fall of 10 blocks does half the time (26.3 javap)."""

_GRAVITY_CLEAR = "fill 1 -60 7 15 -53 9 minecraft:air"

_FALLEN_MOTION = "the ItemEntity constructor sets nextDouble() * 0.2 - 0.1"
GRAVITY_MASKS = tuple(
    Mask(
        "minecraft:add_entity",
        path,
        f"Vanilla draws it at random for the item a falling block breaks into: {draw} (26.3 "
        "javap; Entity.spawnAtLocation). Where the item appears is compared, and which item it "
        "is and how many, in its `set_entity_data`.",
    )
    for path, draw in (
        ("velocity.x", _FALLEN_MOTION),
        ("velocity.z", _FALLEN_MOTION),
        ("yaw", "the ItemEntity constructor sets nextFloat() * 360"),
    )
)
"""How the item a falling block breaks into moves and faces, drawn at random by vanilla. It
appears where the falling block was, so its place is compared."""


@group("blocks/gravity", masks=GRAVITY_MASKS, kind=GroupKind.TICK_EXACT)
async def gravity(context: GroupContext) -> None:
    """Sand, gravel, concrete powder and an anvil fall when the block under them goes."""
    await _play(context, GRAVITY_CASES, _GRAVITY_CLEAR, GRAVITY_PACKETS)


# `blocks/support`: a row of cases along z 12, 2 blocks apart. Each block stands on a block of
# its own at y -60, or hangs on one at z 13, so that removing it leaves the flat world as it was.

SUPPORT_PACKETS = (
    "minecraft:block_update",
    "minecraft:section_blocks_update",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:remove_entities",
    "minecraft:level_event",
    "minecraft:sound",
)
"""What a support window compares: the blocks, the break particles (a world event), the item a
block drops, and sounds. It leaves out how an item moves, which is random."""


def _on(x: int, block: str, *, under: str = "minecraft:stone") -> tuple[str, ...]:
    """The layout of `block` standing at x, -59, 12 on `under`, which a window removes."""
    return (f"setblock {x} -60 12 {under}", f"setblock {x} -59 12 {block}")


def _on_floor(x: int, block: str, *, under: str = "minecraft:stone") -> _Case:
    """`block` on a block of `under`, which the window removes; the block drops an item."""
    return _Case(layout=_on(x, block, under=under), release=f"{x} -60 12", ticks=1, drops=True)


def _on_wall(x: int, block: str) -> _Case:
    """`block` hanging on the north face of a stone, which the window removes."""
    return _Case(
        layout=(f"setblock {x} -59 13 minecraft:stone", f"setblock {x} -59 12 {block}"),
        release=f"{x} -59 13",
        ticks=1,
        drops=True,
    )


SUPPORT_CASES = (
    _on_floor(1, "minecraft:torch"),
    _on_floor(3, "minecraft:rail"),
    _on_floor(5, "minecraft:lever[face=floor,facing=north]"),
    _on_floor(7, "minecraft:poppy", under="minecraft:dirt"),
    _Case(
        layout=(
            *_on(9, "minecraft:oak_door[half=lower,facing=north]"),
            "setblock 9 -58 12 minecraft:oak_door[half=upper,facing=north]",
        ),
        release="9 -60 12",
        ticks=1,
        drops=True,
    ),
    _Case(
        layout=(
            "setblock 11 -60 12 minecraft:stone",
            "setblock 11 -60 13 minecraft:stone",
            "setblock 11 -59 12 minecraft:red_bed[part=foot,facing=south]",
            "setblock 11 -59 13 minecraft:red_bed[part=head,facing=south]",
        ),
        release="11 -60 12",
        ticks=1,
    ),
    _on_wall(13, "minecraft:wall_torch[facing=north]"),
    _on_wall(15, "minecraft:ladder[facing=north]"),
)
"""A torch, a rail, a lever, a poppy, a door and a bed, each on a block, and a wall torch and a
ladder, each on the side of one. Each half of the door and the bed is set by itself.

Each block pops off with its item in the command that removes what holds it up
(`Block.updateOrDestroy`; a rail in `BaseRailBlock.neighborChanged`), and the window steps one
tick, in which nothing more happens (vanilla 26.3, measured). The bed stays: vanilla's needs
nothing under it (`AbstractBedBlock` has no `canSurvive`)."""

_SUPPORT_CLEAR = "fill 1 -60 12 15 -58 13 minecraft:air"


@group("blocks/support", masks=DROP_MASKS, kind=GroupKind.TICK_EXACT)
async def support(context: GroupContext) -> None:
    """Torches, a rail, a lever, a flower, a door, a bed and a ladder lose what holds them up."""
    await _play(context, SUPPORT_CASES, _SUPPORT_CLEAR, SUPPORT_PACKETS)
