"""A probe Group for live tests: Control sets a block inside an Observation window.

Not registered: the live tests play it to show that a window around a Control command
compares what another Bot sees of it, on vanilla and on Pumpkin.
"""

from mscts.group import Group, GroupContext

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
