"""Redstone Groups: when repeaters, comparators, torches, observers, dust and pistons act.

A Bot called `watcher` stands at the spawn. Control stops random ticks, freezes the world and
builds a Group's circuits with `/setblock` on the grass of chunk (0, 0), the one the watcher is
sent first. Then, in an Observation window, Control places or removes the redstone blocks that
feed the circuits and steps the world a tick at a time, so the window compares which blocks change
on which tick: whether a repeater, a comparator or an observer is powered, whether a torch is lit
and how strong each dust is are block states. A piston's move is a block event, then blocks that
move for 2 ticks: docs/research/2026-10-22-pistons.md.

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

from mscts.compare import Mask
from mscts.group import GroupContext, GroupKind, group
from mscts.groups._world import CONTROL_AT, fast_forward, join_at_spawn, pin_joins
from mscts.groups.blocks import DROP_MASKS
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


async def _observe(
    context: GroupContext,
    schedule: tuple[_At, ...],
    ticks: int,
    packets: tuple[str, ...] = _PACKETS,
) -> None:
    """In one window of `packets`, step the world `ticks` ticks, running `schedule` on time."""
    async with context.observe(*packets):
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


# `redstone/comparator`: three comparators at x 3 facing west, so that their rear input is the
# block at x 2, each with 3 dust after it (x 4 to 6), which show the strength of its output.


def _side_input(z: int, toward: int) -> tuple[str, ...]:
    """A redstone block 3 blocks from the comparator at z, and 2 dust from it to its side.

    The dust beside the comparator is 14 strong. `toward` is 1 if the comparator is south of the
    redstone block, -1 if north.
    """
    return (
        _set(3, z - 3 * toward, "redstone_block"),
        _set(3, z - 2 * toward, "redstone_wire"),
        _set(3, z - toward, "redstone_wire"),
    )


def _comparator_at(z: int, mode: str) -> tuple[str, ...]:
    """A comparator in `mode` at x 3, z, facing west, and 3 dust after it."""
    return (
        _set(3, z, f"comparator[facing=west,mode={mode}]"),
        f"fill 4 -60 {z} 6 -60 {z} minecraft:redstone_wire",
    )


_CHEST = "2 -60 13"

_COMPARATOR_BUILD = (
    *_side_input(4, 1),
    *_comparator_at(4, "compare"),
    *_side_input(8, -1),
    *_comparator_at(8, "subtract"),
    f"setblock {_CHEST} minecraft:chest",
    *_comparator_at(13, "compare"),
)
"""At z 4 a comparator in compare mode, its side fed 14 from the north; at z 8 one in subtract
mode, fed 14 from the south; at z 13 one in compare mode that reads an empty chest behind it."""


def _chest_slot(slot: int, stack: str) -> str:
    """Put `stack` in the chest's `slot`, with `/item`."""
    return f"item replace block {_CHEST} container.{slot} with minecraft:{stack}"


_FILLED = (1, 2, 3)
"""The slots filled after the first: 4 stacks of 64 of the chest's 27 slots."""

_COMPARATOR = (
    _At(0, _set(2, 4, "redstone_block")),
    _At(0, _set(2, 8, "redstone_block")),
    _At(4, _set(3, 1, "air")),
    _At(4, _set(3, 11, "air")),
    _At(8, _chest_slot(0, "stone 64")),
    *(_At(12, _chest_slot(slot, "stone 64")) for slot in _FILLED),
    *(_At(16, _chest_slot(slot, "air")) for slot in (0, *_FILLED)),
)
"""A comparator switches 2 ticks after its inputs change (`ComparatorBlock.getDelay`). A rear
input of 15 against a side of 14 gives 15 in compare mode and 1 in subtract mode on tick 2;
without the side input, from tick 4, the subtract one gives 15 on tick 6. A chest with one stack
of 64 gives 1 on tick 10, with four stacks 3 on tick 14, and empty 0 on tick 18
(`AbstractContainerMenu.getRedstoneSignalFromContainer`)."""

_COMPARATOR_TICKS = 19
"""The chest's comparator goes off on tick 18; one tick more."""


@group("redstone/comparator", kind=GroupKind.TICK_EXACT)
async def comparator(context: GroupContext) -> None:
    """Comparators compare and subtract their inputs, and read a chest filled with `/item`."""
    async with _arena(context, _COMPARATOR_BUILD):
        await _observe(context, _COMPARATOR, _COMPARATOR_TICKS)


# `redstone/torch`: two torches, each on a block of stone that Control swaps for a redstone block
# to power it, and back.

_TORCH_BUILD = (
    _set(3, 3, "stone"),
    "setblock 3 -59 3 minecraft:redstone_torch",
    _set(8, 8, "stone"),
    "setblock 8 -59 8 minecraft:redstone_torch",
)

_INVERSION = (_At(0, _set(3, 3, "redstone_block")), _At(4, _set(3, 3, "stone")))
"""A torch turns off 2 ticks after its block is powered, and on 2 ticks after the power goes
(`RedstoneTorchBlock.TOGGLE_DELAY`): off on tick 2, on on tick 6."""

_INVERSION_TICKS = 7

_TOGGLES = 8
"""The times a torch may turn off within 60 ticks (`RedstoneTorchBlock.MAX_RECENT_TOGGLES`)."""

_BURNOUT = tuple(
    at
    for power in range(0, 4 * _TOGGLES, 4)
    for at in (_At(power, _set(8, 8, "redstone_block")), _At(power + 2, _set(8, 8, "stone")))
)
"""The second torch's block is powered every 4 ticks, for 2 ticks, 8 times. The torch turns off
on tick 2 and on tick 4, and so on, until it turns off the 8th time, on tick 30: then it burns
out (level event 1502) and stays off, and ticks again 160 ticks later
(`RedstoneTorchBlock.RESTART_DELAY`)."""

_BURNOUT_TICKS = 31
"""The window ends a tick after the last power goes, on tick 30."""

_RESTART_FAST_FORWARD = 155
"""The ticks stepped at once after the burnout, outside a window: the restart is due 160 ticks
after tick 30, on the 4th step after them."""

_RECOVERY_TICKS = 5


@group("redstone/torch", kind=GroupKind.TICK_EXACT)
async def torch(context: GroupContext) -> None:
    """A torch inverts its block's power; a torch toggled 8 times in 60 ticks burns out."""
    async with _arena(context, _TORCH_BUILD):
        await _observe(context, _INVERSION, _INVERSION_TICKS)
        await _observe(context, _BURNOUT, _BURNOUT_TICKS)
        await fast_forward(context.control, _RESTART_FAST_FORWARD)
        await _observe(context, (), _RECOVERY_TICKS)


# `redstone/observer`: an observer at x 3 that watches the block west of it, and one at x 8 that
# watches the block east of it, where Control places a third observer that watches it back.

_OBSERVER_BUILD = (_set(3, 3, "observer[facing=west]"), _set(8, 8, "observer[facing=east]"))
"""`/setblock` updates a placed block's shape from its neighbours (`BlockInput.place`), which
starts an observer's pulse: both pulse on ticks 2 to 4."""

_OBSERVER = (
    _At(0, _set(2, 3, "stone")),
    _At(6, _set(2, 3, "air")),
    _At(12, _set(9, 8, "observer[facing=west]")),
    _At(24, _set(9, 8, "air")),
)
"""An observer is powered 2 ticks after the block it watches changes, for 2 ticks
(`ObserverBlock.startSignal`, `ObserverBlock.tick`), unless a pulse is already due: the stone
falls inside the first observer's placement pulse, and the air makes it pulse on ticks 8 to 10.
The third observer and the second watch each other: they pulse in turn from tick 14, a clock,
until the third goes on tick 24, and the second is off on tick 26."""

_OBSERVER_TICKS = 30


@group("redstone/observer", kind=GroupKind.TICK_EXACT)
async def observer(context: GroupContext) -> None:
    """An observer pulses when the block it watches changes; two facing each other make a clock."""
    async with _arena(context, _OBSERVER_BUILD):
        await _observe(context, _OBSERVER, _OBSERVER_TICKS)


# `redstone/dust`: a line of dust at z 3 from x 2, which a redstone block at x 1 powers, and a
# lone dust at x 6, z 10, beside which Control builds and cuts a climb.

_DUST_BUILD = (
    "fill 2 -60 3 15 -60 3 minecraft:redstone_wire",
    "fill 15 -60 4 15 -60 5 minecraft:redstone_wire",
    _set(6, 10, "redstone_wire"),
)
"""The line is 16 dust long: 14 along z 3, then 2 along x 15."""


def _raised(x: int, z: int, block: str) -> str:
    """The `/setblock` of `block` at x, -59, z: a block above the grass."""
    return f"setblock {x} -59 {z} minecraft:{block}"


_DUST = (
    _At(0, _set(1, 3, "redstone_block")),
    _At(1, _set(1, 3, "air")),
    _At(2, _set(7, 10, "redstone_wire")),
    _At(3, _set(7, 10, "stone")),
    _At(4, _raised(7, 10, "redstone_wire")),
    _At(5, _raised(6, 10, "stone")),
    _At(6, _raised(6, 10, "air")),
    _At(7, _raised(7, 10, "air")),
    _At(8, _set(7, 10, "air")),
)
"""Dust has no delay: the line's dust is 15 to 1 on tick 1, one less each block, and the 16th
stays 0; all is 0 on tick 2. Then a tick apart: the lone dust connects to dust beside it, is a
cross when the dust is stone, climbs to dust on the stone (`east=up`), is a cross again while
stone above it cuts the climb, then climbs, and is a cross when the climb goes
(`RedstoneWireBlock.getConnectingSide`)."""

_DUST_TICKS = 10


@group("redstone/dust", kind=GroupKind.TICK_EXACT)
async def dust(context: GroupContext) -> None:
    """Dust carries power 15 blocks at once, and connects, climbs and is cut on the next tick."""
    async with _arena(context, _DUST_BUILD):
        await _observe(context, _DUST, _DUST_TICKS)


# `redstone/update-order`: two copies of one case, at x 5 and x 10. In each, a cross of dust at
# z 10 points north and south into stone, and beside each stone, to the west, a piston faces the
# block between them, at z 10: both push into it, so only one can extend.


def _pistons(x: int) -> tuple[str, ...]:
    """The case whose dust is at x, -60, 10: the stones, the pistons, then the dust."""
    return (
        _set(x, 9, "stone"),
        _set(x, 11, "stone"),
        _set(x - 1, 9, "piston[facing=south]"),
        _set(x - 1, 11, "piston[facing=north]"),
        _set(x, 10, "redstone_wire[north=side,south=side,east=side,west=side]"),
    )


_ORDER_AT = (5, 10)
"""The x of each copy's dust. The dust updates its neighbours in the order of a `HashSet` of their
positions, which hashes them by where they are (`DefaultRedstoneWireEvaluator`,
`Vec3i.hashCode`): at x 5 it updates the stone to the north first, at x 10 the one to the south."""

_ORDER_BUILD = tuple(command for x in _ORDER_AT for command in _pistons(x))

_ORDER = (
    *(_At(5 * copy, _raised(x, 10, "redstone_block")) for copy, x in enumerate(_ORDER_AT)),
    *(_At(10 + 5 * copy, _raised(x, 10, "air")) for copy, x in enumerate(_ORDER_AT)),
)
"""A redstone block on each dust powers it, 5 ticks apart, then goes. The piston beside the stone
the dust updates first extends on the next tick: the north one at x 5, the south one at x 10.
The other one's block event finds the block taken and does nothing (`PistonBaseBlock.moveBlocks`).
A piston's head is out 2 ticks after its block event, and it is back 2 ticks after it retracts:
the last on tick 18."""

_ORDER_TICKS = 21

_PISTON_PITCH = Mask(
    "minecraft:sound",
    "pitch",
    "Vanilla draws it at random for a piston (26.3 javap): `PistonBaseBlock.triggerEvent` plays "
    "the extend sound with pitch nextFloat() * 0.25 + 0.6 and the retract sound with "
    "nextFloat() * 0.15 + 0.6. The pistons are the only things that play a sound in the "
    "redstone Groups with this Mask; which sound plays, where and at what volume is still "
    "compared.",
)


@group("redstone/update-order", kind=GroupKind.TICK_EXACT, masks=(_PISTON_PITCH,))
async def update_order(context: GroupContext) -> None:
    """Which of two pistons a dust powers first, by where the dust is."""
    async with _arena(context, _ORDER_BUILD):
        await _observe(context, _ORDER, _ORDER_TICKS)


# The piston Groups: each case a piston at x 2 facing east, unless it says otherwise, so that a
# redstone block Control places at x 1, behind it, powers it, and what it pushes starts at x 3.

_PISTON_PACKETS = (
    *_PACKETS,
    "minecraft:block_entity_data",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
)
"""What a piston window compares: every block that changes, the pistons' block events and
sounds, world events, any block entity's data, and the item a piston breaks a block into."""


def _place(x: int, y: int, z: int, block: str) -> str:
    """The `/setblock` of `block` at x, y, z."""
    return f"setblock {x} {y} {z} minecraft:{block}"


def _piston(z: int, ahead: str, *, y: int = -60, piston: str = "piston") -> tuple[str, ...]:
    """A `piston` at x 2, y, z facing east, and the block `ahead` of it, at x 3."""
    return (_place(2, y, z, f"{piston}[facing=east]"), _place(3, y, z, ahead))


def _power(tick: int, z: int, *, y: int = -60) -> _At:
    """Power the piston at x 2, y, z on `tick`: a redstone block behind it."""
    return _At(tick, _place(1, y, z, "redstone_block"))


def _unpower(tick: int, z: int, *, y: int = -60) -> _At:
    """Take the redstone block behind the piston at x 2, y, z away on `tick`."""
    return _At(tick, _place(1, y, z, "air"))


# `redstone/piston-push`: a row of cases along z.

_STONES = {1: 1, 3: 12, 5: 13}
"""The z of each row of stone in front of a piston, and how long it is."""

_STOPS = {7: "obsidian", 8: "bedrock", 9: "chest", 11: "piston[facing=up,extended=true]"}
"""The z of each block a piston cannot move: one that will not move, one that cannot be broken,
one with a block entity, and an extended piston."""

_POPS = {13: "torch", 15: "poppy"}
"""The z of each block that breaks when a piston pushes it."""

_PUSH_BUILD = (
    *(f"fill 3 -60 {z} {2 + length} -60 {z} minecraft:stone" for z, length in _STONES.items()),
    *(_set(2, z, "piston[facing=east]") for z in _STONES),
    _set(4, 11, "redstone_block"),
    *(command for z, block in _STOPS.items() for command in _piston(z, block)),
    _raised(3, 11, "piston_head[facing=up]"),
    *(command for z, block in _POPS.items() for command in _piston(z, block)),
)
"""The rows of stone and their pistons; the blocks that stop a piston, with the extended
piston's power, a redstone block east of it, placed first so that it does not retract, and its
head; the torch and the poppy on the grass."""

_PUSH_FIRST = (*_STONES, *_STOPS, 13)
"""The rows powered on tick 0: all but the poppy's, powered on tick 2, so that the torch and the
poppy break into their items on ticks of their own."""

_PUSH = (
    *(_power(0, z) for z in _PUSH_FIRST),
    _power(2, 15),
    *(_unpower(4, z) for z in _PUSH_FIRST),
    _unpower(6, 15),
)
"""A piston's block event runs on the next tick: the blocks in front of it become moving blocks,
and they are in place 2 ticks later (`PistonMovingBlockEntity.tick`). 12 stones move; 13 do not,
and neither does a block that is immovable, cannot be broken, has a block entity, or is an
extended piston: that piston has no block event (`PistonStructureResolver.resolve`). The torch and
the poppy break into an item each, on ticks 1 and 3. Each piston retracts on the tick after its
power goes, and is back 2 ticks later: the last on tick 9."""

_PUSH_TICKS = 10

_KILL_ITEMS = "kill @e[type=minecraft:item]"
"""Takes away the items the torch and the poppy broke into, so that the next play has none."""


@group(
    "redstone/piston-push",
    kind=GroupKind.TICK_EXACT,
    masks=(_PISTON_PITCH, *DROP_MASKS),
)
async def piston_push(context: GroupContext) -> None:
    """Pistons push 1 and 12 blocks, not 13 or a block that stops them, and break a torch."""
    async with _arena(context, _PUSH_BUILD):
        try:
            await _observe(context, _PUSH, _PUSH_TICKS, _PISTON_PACKETS)
        finally:
            await context.control.run(_KILL_ITEMS)


# `redstone/sticky`: sticky pistons along z; the two with slime and honey at y -59, above the
# grass, which a slime or honey block would drag along.

_STICKY_PISTON = "sticky_piston"

_SLIME_Z, _HONEY_Z = 6, 10

_STICKY_BUILD = (
    *_piston(1, "stone", piston=_STICKY_PISTON),
    *_piston(3, "stone", piston=_STICKY_PISTON),
    *_piston(_SLIME_Z, "slime_block", y=-59, piston=_STICKY_PISTON),
    _raised(3, _SLIME_Z + 1, "stone"),
    _raised(3, _SLIME_Z - 1, "honey_block"),
    *_piston(_HONEY_Z, "honey_block", y=-59, piston=_STICKY_PISTON),
    _raised(3, _HONEY_Z + 1, "stone"),
    _raised(3, _HONEY_Z - 1, "slime_block"),
)
"""At z 1 and 3 a sticky piston and a stone; at z 6 one that pushes a slime block, with a stone
south of the slime and a honey block north of it; at z 10 one that pushes a honey block, with a
stone south of it and a slime block north."""

_STICKY = (
    _power(0, 1),
    _power(0, 3),
    _power(0, _SLIME_Z, y=-59),
    _power(0, _HONEY_Z, y=-59),
    _unpower(1, 3),
    _unpower(5, 1),
    _unpower(5, _SLIME_Z, y=-59),
    _unpower(5, _HONEY_Z, y=-59),
)
"""Each piston pushes on tick 1. The slime block and the honey block each take the stone beside
them along, and leave the other one (`PistonStructureResolver.canStickToEachOther`). The piston
at z 3 loses its power after 1 tick, while its stone still moves: on tick 2 it retracts with
block event type 2, which puts the stone down where it was pushed (`PistonBaseBlock
.checkIfExtend`, `triggerEvent`), and it is back on tick 4. The others pull theirs back on
tick 6, in place on tick 8."""

_STICKY_TICKS = 9


@group("redstone/sticky", kind=GroupKind.TICK_EXACT, masks=(_PISTON_PITCH,))
async def sticky(context: GroupContext) -> None:
    """Sticky pistons pull back, drop their block after a 1-tick pulse, and move slime and honey."""
    async with _arena(context, _STICKY_BUILD):
        await _observe(context, _STICKY, _STICKY_TICKS, _PISTON_PACKETS)


# `redstone/quasi-connectivity`: a piston, a dropper and a dispenser at x 3, facing east, each
# with a redstone block 2 above it, at y -58, and stone that Control places behind it, at x 2.

_QUASI = {"piston": 3, "dropper": 7, "dispenser": 11}
"""The z of each block that reads power at the block above it."""

_QUASI_BUILD = tuple(_set(3, z, f"{block}[facing=east]") for block, z in _QUASI.items())


def _two_above(z: int, block: str) -> str:
    """The `/setblock` of `block` 2 above the block at x 3, -60, z."""
    return _place(3, -58, z, block)


_QUASI_SCHEDULE = (
    *(_At(0, _two_above(z, "redstone_block")) for z in _QUASI.values()),
    *(_At(2, _set(2, z, "stone")) for z in _QUASI.values()),
    *(_At(8, _two_above(z, "air")) for z in _QUASI.values()),
    *(_At(10, _set(2, z, "air")) for z in _QUASI.values()),
)
"""A piston, a dropper and a dispenser count power next to the block above them as their own
(`PistonBaseBlock.getNeighborSignal`, `DispenserBlock.neighborChanged`), but check it only when
a block next to them changes. A redstone block 2 above changes only the blocks next to it, so
nothing acts on it; the stone placed behind each, on tick 2, makes them check: the piston
extends on tick 3, and the dropper and the dispenser are triggered at once and click 4 ticks
later, on tick 6 (world event 1001: they are empty). The redstone blocks go on tick 8, and
nothing changes until the stones go on tick 10: the piston retracts, back on tick 13, and the
dropper and the dispenser are no longer triggered."""

_QUASI_TICKS = 14


@group("redstone/quasi-connectivity", kind=GroupKind.TICK_EXACT, masks=(_PISTON_PITCH,))
async def quasi_connectivity(context: GroupContext) -> None:
    """A piston, a dropper and a dispenser powered 2 blocks above act only once updated."""
    async with _arena(context, _QUASI_BUILD):
        await _observe(context, _QUASI_SCHEDULE, _QUASI_TICKS, _PISTON_PACKETS)
