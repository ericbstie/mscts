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
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from mscts.bot import Bot, Face
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
INVENTORY_0 = 9
"""The inventory menu's slot for `inventory.0`, the first of the 27."""
TABLE_INVENTORY_0 = 10
"""A crafting table's slot for `inventory.0` (`CraftingMenu`: the result and the 3x3 come
first)."""
RESULT = 0
"""The crafting result's slot, in the inventory menu and in a crafting table."""


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

TAKES = 2
"""How many times the Bot clicks a result, each in a window of its own: onto an empty cursor,
then onto what it took."""
INVENTORY_TAKE = (Grid("minecraft:oak_log", 2, (1, 1)),)
"""The stacks the Bot crafts from in its 2x2 grid: two logs in one cell, planks for two takes,
which stack on the cursor."""
TABLE_TAKE = (
    Grid("minecraft:cobblestone", 6, (1, 1, 2, 2, 3, 3)),
    Grid("minecraft:stick", 4, (5, 5, 8, 8)),
)
"""The stacks the Bot crafts from in a crafting table: a stone pickaxe's (shaped), twice over.
A pickaxe does not stack, so the second take finds no room on the cursor and takes nothing."""


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
        await _spread(bot, HOTBAR_0, case.slots)


async def _spread(bot: Bot, slot: int, cells: tuple[int, ...]) -> None:
    """Pick up the stack in `slot`, right-click one item onto each of `cells`, put the rest back."""
    await bot.click(slot)
    for cell in cells:
        await bot.click(cell, 1)
    if bot.inventory.carried is not None:
        await bot.click(slot)


async def _take(context: GroupContext, bot: Bot, stacks: tuple[Grid, ...], first: int) -> None:
    """Put `stacks` on the open grid in one window, then click its result `TAKES` times.

    The stacks start in the menu's slots from `first` on (`inventory.0`). Each take has a
    window of its own, which waits for the server's next result. The last also puts what the
    cursor holds back in `first`, which the stacks emptied.
    """
    async with context.observe(*PACKETS):
        for index, stack in enumerate(stacks):
            await _spread(bot, first + index, stack.slots)
    for take in range(1, TAKES + 1):
        async with context.observe(*PACKETS):
            await bot.click(RESULT)
            if take == TAKES:
                await bot.click(first)


def _items(stacks: tuple[Grid, ...]) -> tuple[str, ...]:
    """The stacks as `_fill` gives them: an item and a count each."""
    return tuple(f"{stack.item} {stack.count}" for stack in stacks)


@group("crafting/grid")
async def grid(context: GroupContext) -> None:
    """Items clicked into the 2x2 grid or a crafting table's 3x3 show a result, or none."""
    async with contextlib.AsyncExitStack() as undo:
        bot = await _stage(context, undo, CRAFTER)
        for case in GRID_CASES:
            await _put(context, bot, case)
        await _fill(context, bot.name, _items(INVENTORY_TAKE))
        await _take(context, bot, INVENTORY_TAKE, INVENTORY_0)
        await _set_table(context, undo, bot)
        await _fill(context, bot.name, _items(TABLE_TAKE))
        await _open_table(bot)
        await _take(context, bot, TABLE_TAKE, TABLE_INVENTORY_0)
        await _close_table(bot)


# `crafting/recipe-book`

BOOKWORM = "bookworm"
"""The Bot of `crafting/recipe-book`."""

TABLE = (12, -60, 14)
"""Where the crafting table stands, two blocks south of where the Bot uses it."""
_TABLE_STAND = "12.5 -60 12.5"
"""Where the Bot stands to use the table, facing south."""

BOOK_RECIPES = (
    "minecraft:oak_planks",
    "minecraft:crafting_table",
    "minecraft:stone_pickaxe",
    "minecraft:stick",
)
"""The recipes the Bot is given one at a time, to read their display ids from `recipe_book_add`."""

LOCKED = "minecraft:stick"
"""The recipe taken from the book again before the cases: a click on it places nothing."""

_BOOK_TIMEOUT_S = 10.0
"""How long the Bot waits for the book entry of a recipe it is given."""


@dataclass(frozen=True, slots=True)
class Placement:
    """One click in the recipe book: the recipe, and whether it asks for as many as it can.

    `items` are the stacks in the Bot's inventory before the click, from `inventory.0` on,
    each an item and a count.
    """

    recipe: str
    items: tuple[str, ...]
    use_max_items: bool = False


INVENTORY_PLACEMENTS = (
    Placement("minecraft:oak_planks", ("minecraft:oak_log 2",)),
    Placement("minecraft:oak_planks", ("minecraft:oak_log 2",), use_max_items=True),
    Placement("minecraft:crafting_table", ("minecraft:oak_planks 2",)),
    Placement(LOCKED, ("minecraft:oak_planks 2",)),
)
"""The clicks in the inventory's 2x2 grid: one placement, all of it, too few items for a
crafting table (a ghost recipe), and a recipe the Bot does not know."""

TABLE_PLACEMENTS = (
    Placement("minecraft:stone_pickaxe", ("minecraft:cobblestone 3", "minecraft:stick 2")),
    Placement("minecraft:stone_pickaxe", ("minecraft:cobblestone 1", "minecraft:stick 2")),
    Placement("minecraft:crafting_table", ("minecraft:oak_planks 8",), use_max_items=True),
    Placement(LOCKED, ("minecraft:oak_planks 2",)),
)
"""The clicks in a crafting table's 3x3 grid: a pickaxe, a pickaxe with too few items, two
crafting tables at once, and a recipe the Bot does not know."""

FIRST_ITEMS = (
    "minecraft:oak_log 2",
    "minecraft:oak_planks 8",
    "minecraft:cobblestone 3",
    "minecraft:stick 2",
)
"""Every item a placement uses, given once before the recipes are taken: an item a player
first gets unlocks recipes (vanilla's `recipes/` advancements), once per player, so no
placement's items unlock one."""


async def _fill(context: GroupContext, name: str, items: tuple[str, ...]) -> None:
    """Empty the Bot `name` and put `items` in its inventory, from `inventory.0` on."""
    control = context.control
    await control.run(f"clear {name}")
    for index, item in enumerate(items):
        await control.run(f"item replace entity {name} inventory.{index} with {item}")


async def _give_and_read_id(context: GroupContext, bot: Bot, recipe: str) -> int:
    """Give the Bot `recipe` and read the display id its recipe book entry has."""
    await context.control.run(f"recipe give {bot.name} {recipe}")
    try:
        packet = await bot.expect("minecraft:recipe_book_add", timeout_s=_BOOK_TIMEOUT_S)
    except TimeoutError:
        msg = f"{recipe} was given, but no recipe_book_add came within {_BOOK_TIMEOUT_S} s"
        raise TimeoutError(msg) from None
    entries = cast("list[Mapping[str, object]]", (packet.fields or {})["entries"])
    if len(entries) != 1:
        msg = f"{recipe} was given, but its recipe_book_add held {len(entries)} entries, not 1"
        raise ValueError(msg)
    return cast("int", cast("Mapping[str, object]", entries[0]["contents"])["id"])


async def _click(context: GroupContext, bot: Bot, ids: Mapping[str, int], case: Placement) -> None:
    """Click the recipe of `case` in the book, inside a window."""
    async with context.observe(*PACKETS):
        await bot.place_recipe(ids[case.recipe], use_max_items=case.use_max_items)


async def _set_table(context: GroupContext, undo: contextlib.AsyncExitStack, bot: Bot) -> None:
    """Set a crafting table two blocks south of where the Bot is put to use it.

    The undo also puts back the grass under the table: a random tick turns grass under an
    opaque block to dirt, on one Instance and not another, which `join/basic` then sees.
    """
    control = context.control
    x, y, z = TABLE
    undo.push_async_callback(control.run, f"setblock {x} {y - 1} {z} minecraft:grass_block")
    undo.push_async_callback(control.run, f"setblock {x} {y} {z} minecraft:air")
    await control.run(f"setblock {x} {y} {z} minecraft:crafting_table")
    await control.run(f"tp {bot.name} {_TABLE_STAND} 0 0")


async def _in_table(
    context: GroupContext, bot: Bot, ids: Mapping[str, int], case: Placement
) -> None:
    """Open the table, click the recipe of `case`, and close the table.

    Closing the table gives back what its grid holds, so each case starts from an empty grid.
    The window's opening barrier covers the table's `open_screen`. The barrier after the close
    makes the server give the grid back before Control's next `/clear`: the Bot and Control
    are separate connections, and nothing else orders the two.
    """
    await _fill(context, bot.name, case.items)
    await _open_table(bot)
    await _click(context, bot, ids, case)
    await _close_table(bot)


async def _open_table(bot: Bot) -> None:
    """Use the crafting table, from where `_set_table` put the Bot."""
    x, y, z = TABLE
    await bot.place(x, y, z, Face.NORTH, (0.5, 0.5, 0.0))


async def _close_table(bot: Bot) -> None:
    """Close the table, and wait until the server has given back what its grid held."""
    await bot.close_container()
    await bot.sync()


@group("crafting/recipe-book")
async def recipe_book(context: GroupContext) -> None:
    """Clicks in the recipe book fill the 2x2 and 3x3 grids, or show a ghost recipe."""
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        bot = await _stage(context, undo, BOOKWORM)
        await _fill(context, bot.name, FIRST_ITEMS)
        await control.run(f"recipe take {bot.name} *")
        await bot.sync()
        ids = {recipe: await _give_and_read_id(context, bot, recipe) for recipe in BOOK_RECIPES}
        await control.run(f"recipe take {bot.name} {LOCKED}")
        for case in INVENTORY_PLACEMENTS:
            await _fill(context, bot.name, case.items)
            await _click(context, bot, ids, case)
        await _set_table(context, undo, bot)
        for case in TABLE_PLACEMENTS:
            await _in_table(context, bot, ids, case)


# `crafting/unlocking`

LEARNER = "learner"
"""The Bot of `crafting/unlocking`."""

BOOK_CHANGES = (
    "recipe give {name} minecraft:stick",
    "recipe take {name} minecraft:stick",
    "recipe give {name} *",
    "recipe take {name} *",
)
"""The `recipe` commands that each change the Bot's book inside a window: one recipe given and
taken, then every recipe."""

OAK_PLANKS_ADVANCEMENT = "minecraft:recipes/building_blocks/oak_planks"
"""The advancement that gives the oak planks recipe to a player who gets an oak log."""


async def _change_book(context: GroupContext, bot: Bot) -> None:
    """Run each of `BOOK_CHANGES` on the Bot, each inside a window."""
    for command in BOOK_CHANGES:
        async with context.observe(*PACKETS):
            await context.control.run(command.format(name=bot.name))


async def _unlock_by_item(context: GroupContext, bot: Bot) -> None:
    """Give the Bot, who knows no recipe, an oak log inside a window, which unlocks oak planks.

    The advancement is revoked first, so that the log unlocks the recipe again.
    """
    control = context.control
    await control.run(f"clear {bot.name}")
    await control.run(f"advancement revoke {bot.name} only {OAK_PLANKS_ADVANCEMENT}")
    await control.run(f"recipe take {bot.name} *")
    async with context.observe(*PACKETS):
        await control.run(f"give {bot.name} minecraft:oak_log")


async def _limited(context: GroupContext, bot: Bot, *, limited: bool) -> None:
    """With `limited_crafting` set to `limited`, click an oak log into the 2x2 grid.

    The Bot knows no recipe, so a server that limits crafting shows no planks.
    """
    control = context.control
    await control.run(f"gamerule limited_crafting {str(limited).lower()}")
    await control.run(f"clear {bot.name}")
    await control.run(f"item replace entity {bot.name} hotbar.0 with minecraft:oak_log 1")
    async with context.observe(*PACKETS):
        await bot.click(HOTBAR_0)
        await bot.click(1)


@group("crafting/unlocking")
async def unlocking(context: GroupContext) -> None:
    """Recipes given, taken and unlocked by an item change the book, and limit crafting."""
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        bot = await _stage(context, undo, LEARNER)
        name = bot.name
        await control.run(f"item replace entity {name} hotbar.0 with minecraft:oak_log 1")
        await control.run(f"recipe take {name} *")
        await control.run(f"clear {name}")
        await _change_book(context, bot)
        undo.push_async_callback(control.run, "gamerule limited_crafting false")
        for limited in (True, False):
            await _limited(context, bot, limited=limited)
        await _unlock_by_item(context, bot)
