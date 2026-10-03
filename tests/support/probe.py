"""Probe Groups for live tests: Control changes blocks inside an Observation window.

Not registered: the live tests play them to show that a window around a Control command
compares what another Bot sees of it, on vanilla and on Pumpkin, and that a tick-exact Group
compares it tick by tick.
"""

from mscts.group import Group, GroupContext, GroupKind

BLOCK = "1 -60 1"
"""Where the probe sets a block: in the spawn chunk, just above the flat world's grass."""

WATCHER = "watcher"
"""The probe's own Bot, which sees the block change."""


async def _setblock_observed(context: GroupContext) -> None:
    """Control sets a block inside a window; the watcher sees it change."""
    watcher = await context.bot(WATCHER)
    await watcher.join()
    await context.control.run("tick freeze")
    async with context.observe("minecraft:block_update"):
        await context.control.run(f"setblock {BLOCK} minecraft:stone")
    await context.control.run(f"setblock {BLOCK} minecraft:air")


SETBLOCK_OBSERVED = Group(id="probe/setblock-observed", run=_setblock_observed)
"""A probe Group, not registered: a Bot, and an Observation window around one command."""


REPEATER_ROW = 4
"""The z of the probe's redstone row, at y = -60, in the spawn chunk."""

STEPS = 10
"""How many ticks the redstone probe steps: past the repeater's delay of 4 ticks."""

WATCHER_AT = "0.5 -60 14.5"
"""Where the watcher stands: in the spawn chunk, clear of the redstone row."""


async def _repeater_stepped(context: GroupContext) -> None:
    """A redstone block powers a repeater and its dust, observed tick by tick.

    Control lays a repeater (input at x = 1, delay 2, so 4 ticks) and dust after it, then,
    in a window, sets the redstone block that powers the repeater and steps 10 ticks. The
    watcher sees each block change on the tick it happened.
    """
    watcher = await context.bot(WATCHER)
    await watcher.join()
    await context.control.run(f"tp {WATCHER} {WATCHER_AT}")
    await context.freeze()
    row = REPEATER_ROW
    await context.control.run(f"setblock 2 -60 {row} minecraft:repeater[facing=west,delay=2]")
    await context.control.run(f"fill 3 -60 {row} 5 -60 {row} minecraft:redstone_wire")
    async with context.observe("minecraft:block_update", "minecraft:section_blocks_update"):
        await context.control.run(f"setblock 1 -60 {row} minecraft:redstone_block")
        await context.step(STEPS)
    await context.control.run(f"fill 1 -60 {row} 5 -60 {row} minecraft:air")


REPEATER_STEPPED = Group(
    id="probe/repeater-stepped", run=_repeater_stepped, kind=GroupKind.TICK_EXACT
)
"""A tick-exact probe Group, not registered: a repeater and dust powered, stepped 10 ticks."""
