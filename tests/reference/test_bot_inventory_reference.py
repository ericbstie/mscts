"""A Bot's inventory against a live vanilla 26.3: what it holds after gives, a chest and a drop.

Boots a Reference of its own, since Control gives items and places a chest.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest

from mscts.bot import Face
from mscts.group import GroupContext
from mscts.inventory import Stack
from mscts.runner import Instance
from mscts.transcript import Transcript

pytestmark = pytest.mark.reference

_TIMEOUT_S = 10.0
HOLDER = "holder"
CHEST = (2, -60, 0)
"""On the flat world's grass, two blocks east of where the holder stands, in reach."""

SETUP = (
    "tp holder 0.5 -60 0.5 0 0",
    "give holder minecraft:stone 64",
    "give holder minecraft:diamond_sword",
    "setblock 2 -60 0 minecraft:chest",
)


@pytest.mark.timeout(180)  # its own boot and stop, a join, four commands and a few barriers
@pytest.mark.asyncio
async def test_a_bots_inventory_follows_gives_a_chest_and_a_drop(
    boot_reference: Callable[..., AbstractAsyncContextManager[Instance]],
) -> None:
    transcript = Transcript(group_id="reference/bot-inventory", server="vanilla")
    async with boot_reference() as reference:
        context = GroupContext(reference.endpoint, transcript, timeout_s=_TIMEOUT_S)
        try:
            holder = await context.bot(HOLDER)
            await holder.join()
            for command in SETUP:
                await context.control.run(command)
            await holder.sync()
            given = holder.inventory
            await holder.place(*CHEST, Face.UP)  # the use opens the chest
            await holder.sync()
            chest = holder.inventory
            await holder.close_container()
            await holder.drop()
            await holder.sync()
            dropped = holder.inventory
        finally:
            await context.close()

    stone, sword = Stack("minecraft:stone", 64), Stack("minecraft:diamond_sword", 1)
    # /give fills the selected hotbar slot, 0, then the next empty one.
    assert (given.window_id, given.menu, given.slots[36], given.slots[37]) == (
        0,
        None,
        stone,
        sword,
    )
    assert given.player[:2] == (stone, sword)
    # A single chest: its 27 empty slots, then the player's 27, then the hotbar.
    assert (chest.menu, len(chest.slots)) == ("minecraft:generic_9x3", 63)
    assert chest.window_id > 0
    assert chest.slots[:27] == (None,) * 27
    assert chest.slots[54:56] == (stone, sword)
    assert (dropped.window_id, dropped.player[0]) == (0, Stack("minecraft:stone", 63))
