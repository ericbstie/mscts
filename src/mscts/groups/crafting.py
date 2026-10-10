"""Crafting Groups: the crafting grid's result, the recipe book filling the grid, and unlocks.

Each Group joins one Bot in survival, empties its inventory, and has Control put the items each
case needs in it. Control stands far away (`_world.CONTROL_AT`): it is a player too, with a
recipe book of its own. The Bot is emptied and put back at the spawn when the Group ends,
because every Group is played on the same two Instances, which keep each player's inventory
and recipe book from one play to the next.

A crafting result is sent only to the player crafting, in the window of the grid it uses (0 for
the 2x2 grid of the inventory).
"""

import contextlib
from dataclasses import dataclass

from mscts.bot import Bot
from mscts.group import GroupContext, group
from mscts.groups._world import CONTROL_AT, join_at_spawn, pin_joins
from mscts.spec import CONTROL_PLAYER

PACKETS = (
    "minecraft:container_set_slot",
    "minecraft:container_set_content",
    "minecraft:set_cursor_item",
    "minecraft:place_ghost_recipe",
    "minecraft:recipe_book_add",
    "minecraft:recipe_book_remove",
    "minecraft:update_recipes",
)
"""What every window compares: the slots and the cursor as the server sets them, the ghost
recipe the grid shows, and the recipes added to and taken from the recipe book."""

CRAFTER = "crafter"
"""The Bot of `crafting/grid`."""

HOTBAR_0 = 36
"""The inventory menu's slot for the first hotbar slot (`InventoryMenu`: the result, the 2x2,
the armor and the 27 come first)."""


@dataclass(frozen=True, slots=True)
class Grid:
    """One case of the 2x2 grid: a stack in the first hotbar slot, one item put on each cell.

    `count` of `item` start in the slot; `slots` are the cells (1 and 2 the top row, 3 and 4
    the bottom one).
    """

    item: str
    count: int
    slots: tuple[int, ...]


GRID_CASES = (
    Grid("minecraft:oak_log", 1, (1,)),
    Grid("minecraft:oak_planks", 2, (1, 3)),
    Grid("minecraft:oak_planks", 4, (1, 2, 3, 4)),
    Grid("minecraft:bone", 1, (4,)),
    Grid("minecraft:oak_planks", 2, (1, 4)),
    Grid("minecraft:dirt", 1, (2,)),
)
"""Planks from a log, sticks, a crafting table (shaped), bone meal from a bone (shapeless, in
any cell), and two arrangements that make nothing: planks on a diagonal, and dirt."""


async def _stage(context: GroupContext, undo: contextlib.AsyncExitStack, name: str) -> Bot:
    """Pin the joins, move Control away, join the Bot and empty it; undo it all on exit."""
    control = context.control
    await pin_joins(control, undo)
    await control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
    bot = await join_at_spawn(context, undo, name)
    undo.push_async_callback(control.run, f"clear {name}")
    await control.run(f"clear {name}")
    return bot


async def _put(context: GroupContext, bot: Bot, case: Grid) -> None:
    """Play one 2x2 case: empty the Bot, give it the stack, and click it into the grid.

    Inside the window the Bot picks the stack up, right-clicks one item onto each cell, and
    puts what is left back. The server answers with the result slot (slot 0).
    """
    control = context.control
    await control.run(f"clear {bot.name}")
    await control.run(f"item replace entity {bot.name} hotbar.0 with {case.item} {case.count}")
    async with context.observe(*PACKETS):
        await bot.click(HOTBAR_0)
        for slot in case.slots:
            await bot.click(slot, 1)
        if bot.inventory.carried is not None:
            await bot.click(HOTBAR_0)


@group("crafting/grid")
async def grid(context: GroupContext) -> None:
    """Items clicked into the inventory's 2x2 grid show a result, or none."""
    async with contextlib.AsyncExitStack() as undo:
        bot = await _stage(context, undo, CRAFTER)
        for case in GRID_CASES:
            await _put(context, bot, case)
