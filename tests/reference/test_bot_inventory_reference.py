"""A Bot's inventory against a live vanilla 26.3: gives, a chest, a drop and a furnace.

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


SMELTER = "smelter"
FURNACE = (2, -60, 0)


@pytest.mark.timeout(180)  # its own boot and stop, a join, three commands and a few barriers
@pytest.mark.asyncio
async def test_a_give_with_a_furnace_open_shows_in_the_hotbar_once_it_closes(
    boot_reference: Callable[..., AbstractAsyncContextManager[Instance]],
) -> None:
    # ServerPlayer.tick broadcasts only the open menu: the give comes through the furnace's
    # window, at its player slot 30, and nothing resends it for window 0 after the close.
    transcript = Transcript(group_id="reference/bot-inventory-furnace", server="vanilla")
    async with boot_reference() as reference:
        context = GroupContext(reference.endpoint, transcript, timeout_s=_TIMEOUT_S)
        try:
            smelter = await context.bot(SMELTER)
            await smelter.join()
            await context.control.run("tp smelter 0.5 -60 0.5 0 0")
            await context.control.run("setblock 2 -60 0 minecraft:furnace")
            await smelter.sync()
            await smelter.place(*FURNACE, Face.UP)  # an empty hand's use opens the furnace
            await smelter.sync()
            await context.control.run("give smelter minecraft:stone 5")
            await smelter.sync()
            opened = smelter.inventory
            await smelter.close_container()
            await smelter.sync()
            closed = smelter.inventory
        finally:
            await context.close()

    stone = Stack("minecraft:stone", 5)
    assert (opened.menu, len(opened.slots), opened.slots[30]) == ("minecraft:furnace", 39, stone)
    assert (closed.window_id, closed.player[0], closed.slots[36]) == (0, stone, stone)
