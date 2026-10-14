"""Inventory Groups: what a player sees when it is given items, clicks them and drops them.

Each Group joins one Bot, in survival, at the world spawn, looking down, with nothing in its
inventory. Control stands 6 chunks away, out of the Bot's view, and freezes the world, so an
item that appears stays where it is: a thrown item counts down its pickup delay only on the
ticks a Group steps. When the Group ends, Control removes the items it made (and only those:
what lay there before is tagged first), empties the Bot's inventory, puts the Bot back at the
spawn and sets every rule back, because every Group is played on the same two Instances.
"""

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass

from mscts.bot import Bot, Face
from mscts.compare import Mask
from mscts.group import GroupContext, GroupKind, group
from mscts.groups._world import CONTROL_AT, SPAWN_AT, join_at_spawn, pin_joins
from mscts.spec import CONTROL_PLAYER


def _items(*filters: str) -> str:
    """The selector of the items within 20 blocks of the spawn that also match `filters`."""
    return f"@e[{','.join(('type=minecraft:item,x=0.5,y=-60,z=0.5,distance=..20', *filters))}]"


_BEFORE = "mscts_inventory_before"
"""The tag an item already there carries while a Group plays."""

_KILL_NEW_ITEMS = f"kill {_items(f'tag=!{_BEFORE}')}"

_THROW = (
    "LivingEntity.createItemStackToDrop gives an item a player drops the motion "
    "(-sin(yaw) cos(pitch) 0.3 + cos(a) h, -sin(pitch) 0.3 + 0.1 + (nextFloat() - nextFloat()) "
    "0.1, cos(yaw) cos(pitch) 0.3 + sin(a) h) with a = nextFloat() * 2 pi and "
    "h = nextFloat() * 0.02, and the ItemEntity constructor sets its yaw to nextFloat() * 360"
)

DROP_MASKS = tuple(
    Mask(
        "minecraft:add_entity",
        path,
        f"Vanilla draws it at random for every item a player drops: {_THROW} (26.3 javap). "
        "Where the item appears is compared (the player's eyes, less 0.3), and so are its type "
        "and count in `set_entity_data`; how it moves belongs to `entities/motion`.",
    )
    for path in ("velocity.x", "velocity.y", "velocity.z", "yaw")
)
"""How an item a player drops moves and faces, drawn at random by vanilla."""

PICKUP_PITCH = Mask(
    "minecraft:sound",
    "pitch",
    "Vanilla draws it at random for the pickup sound of a `/give` (26.3 javap): "
    "`GiveCommand.giveItem` plays ITEM_PICKUP with pitch ((nextFloat() - nextFloat()) * 0.7 "
    "+ 1) * 2. Which sound plays, where and at what volume is still compared.",
)
"""The pitch of the pickup sound that `/give` plays."""


@contextlib.asynccontextmanager
async def _arena(context: GroupContext, name: str) -> AsyncIterator[Bot]:
    """Join the Bot `name` empty, in survival, at the spawn looking down; freeze the world.

    Undoes it all on exit, each undo even if another fails: the new items go first, before the
    Bot is emptied, since a player picks up an item with no pickup delay as soon as it has room.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        await control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
        await control.run(f"tag {_items()} add {_BEFORE}")
        undo.push_async_callback(control.run, f"tag {_items()} remove {_BEFORE}")
        bot = await join_at_spawn(context, undo, name)
        undo.push_async_callback(control.run, f"clear {name}")
        undo.push_async_callback(control.run, _KILL_NEW_ITEMS)
        await control.run(f"gamemode survival {name}")
        await control.run(f"clear {name}")
        await control.run(f"tp {name} {SPAWN_AT} 0 90")
        await context.freeze()
        yield bot


async def _empty(context: GroupContext, name: str) -> None:
    """Remove the items the Group made, then empty the Bot's inventory."""
    await context.control.run(_KILL_NEW_ITEMS)
    await context.control.run(f"clear {name}")


# `inventory/give`

_GIVER = "giver"

GIVE_PACKETS = (
    "minecraft:container_set_content",
    "minecraft:container_set_slot",
    "minecraft:set_cursor_item",
    "minecraft:set_player_inventory",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:take_item_entity",
    "minecraft:remove_entities",
    "minecraft:sound",
)
"""What a give window compares: the inventory, the item that appears and goes, and the sound."""

_SEVERAL_ITEMS_PACKETS = tuple(name for name in GIVE_PACKETS if name != "minecraft:set_entity_data")
"""What a window that makes several items compares. Vanilla sends each new item's data again at
the end of the tick, in the hash order of its entity id (`ChunkMap.tick` over `entityMap`), and
two servers can number their entities differently. The slots show what was given; which entity
carried which stack is not compared."""


@dataclass(frozen=True, slots=True)
class _Give:
    """One `/give`: the item and the count, into an empty inventory or a `full` one.

    `several_entities` says the give makes more than one item entity, so its window leaves out
    their data: `GiveCommand.giveItem` gives a stack at a time, and each stack makes an item
    entity of its own.
    """

    item: str
    count: int
    full: bool = False
    several_entities: bool = False

    def packets(self) -> tuple[str, ...]:
        """What the give's window compares."""
        return _SEVERAL_ITEMS_PACKETS if self.several_entities else GIVE_PACKETS


_FULL = f"give {_GIVER} minecraft:dirt 2304"
"""Fills the 36 slots of the Bot's inventory with stacks of 64 dirt (the off hand stays empty)."""

GIVES = (
    _Give("minecraft:stone", 1),
    _Give("minecraft:stone", 64),
    _Give("minecraft:stone", 100, several_entities=True),
    _Give("minecraft:diamond_sword", 1),
    _Give("minecraft:stone", 1, full=True),
)
"""The gives, one window each: one stack, a full stack, more than a stack, an unstackable item,
and an item that does not fit, which drops. Each window steps one tick: a give that fits shows an
item popping out of the player that nobody can pick up (`ItemEntity.makeFakeItem`, age 5999), and
vanilla removes it on its next tick."""


@group("inventory/give", masks=(*DROP_MASKS, PICKUP_PITCH))
async def give(context: GroupContext) -> None:
    """Control gives the Bot stone, a sword, and stone that does not fit, in a window each."""
    async with _arena(context, _GIVER):
        for case in GIVES:
            await _empty(context, _GIVER)
            if case.full:
                await context.control.run(_FULL)
            async with context.observe(*case.packets()):
                await context.control.run(f"give {_GIVER} {case.item} {case.count}")
                await context.step(1)


# `inventory/drop`

_DROPPER = "dropper"

DROP_PACKETS = (
    "minecraft:container_set_slot",
    "minecraft:set_player_inventory",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:take_item_entity",
    "minecraft:remove_entities",
    "minecraft:sound",
)
"""The packets a drop window compares: the slot, the item thrown, and the item picked up."""

PICKUP_TICKS = 41
"""How many ticks a window steps to see the thrown item picked up. Its pickup delay is 40
(`LivingEntity.createItemStackToDrop`), counted down only on the ticks the frozen world steps,
and the Bot, which looks down, stands on it: it is picked up on the 40th. The 41st shows that
nothing follows."""


@dataclass(frozen=True, slots=True)
class _Drop:
    """One press of Q: what the Bot holds, whether Ctrl is held (`all`), how many ticks follow."""

    held: str
    all: bool = False
    ticks: int = 1


DROPS = (
    _Drop("minecraft:stone 64", ticks=PICKUP_TICKS),
    _Drop("minecraft:stone 64", all=True),
    _Drop("minecraft:diamond_sword 1"),
    _Drop("minecraft:air"),
)
"""The drops, one window each: one stone of a stack, until the Bot picks it up again; the whole
stack; an unstackable item; and an empty hand. Only the first steps until the pickup: a step
takes about 0.3 s of the play's time."""


@group("inventory/drop", masks=DROP_MASKS, kind=GroupKind.TICK_EXACT)
async def drop(context: GroupContext) -> None:
    """The Bot drops a stone and picks it up again, then drops a stack, a sword and nothing."""
    async with _arena(context, _DROPPER) as bot:
        for case in DROPS:
            await _empty(context, _DROPPER)
            await context.control.run(f"item replace entity {_DROPPER} hotbar.0 with {case.held}")
            async with context.observe(*DROP_PACKETS):
                await bot.drop(all=case.all)
                await context.step_after(bot, ticks=case.ticks)


# `inventory/clicks-inventory` and `inventory/clicks-chest`

_CLICKER = "clicker"

CHEST = (2, -60, 0)
"""Where the chest stands: next to the Bot, in the chunk it joined in."""

CLICK_PACKETS = (
    "minecraft:open_screen",
    "minecraft:container_set_content",
    "minecraft:container_set_slot",
    "minecraft:set_cursor_item",
    "minecraft:set_player_inventory",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:sound",
)
"""The packets a click window compares: the menus, an item thrown out, and a sound. When the
Bot predicts a click right, vanilla sends nothing back, so an empty window is a match too."""

CHEST_PITCH = Mask(
    "minecraft:sound",
    "pitch",
    "Vanilla draws it at random for a chest opening or closing (26.3 javap): "
    "`ChestBlockEntity.playSound` plays it with pitch nextFloat() * 0.1 + 0.9. The Mask hides "
    "the pitch of every sound in `inventory/clicks-chest`, where the chest is the only thing "
    "that plays one; which sound plays, where and at what volume is still compared.",
)
"""The pitch of the sound a chest makes when it opens. Only `inventory/clicks-chest` has it, so
the fixed pitch of an armor's equip sound is compared in `inventory/clicks-inventory`."""

_CHEST_ITEMS = (
    '{Slot:0b,id:"minecraft:stone",count:10}',
    '{Slot:1b,id:"minecraft:dirt",count:64}',
    '{Slot:2b,id:"minecraft:diamond_sword",count:1}',
    '{Slot:3b,id:"minecraft:stone",count:5}',
    '{Slot:4b,id:"minecraft:oak_log",count:3}',
)
_CHEST = f"minecraft:chest[facing=west]{{Items:[{','.join(_CHEST_ITEMS)}]}}"
"""The chest, facing the Bot, and what is in it."""

KIT = (
    "hotbar.0 with minecraft:stone 32",
    "hotbar.1 with minecraft:oak_log 16",
    "inventory.0 with minecraft:dirt 20",
    "inventory.2 with minecraft:diamond_helmet 1",
    "inventory.3 with minecraft:stone 64",
    "weapon.offhand with minecraft:torch 8",
)
"""What the Bot holds before its first click in each Group, set with `/item replace`."""

type Click = tuple[int, int, str]
"""A click: the slot, the button and the mode, as `Bot.click` takes them."""

_OUT = -999
"""The slot of a click outside the window (`AbstractContainerMenu.SLOT_CLICKED_OUTSIDE`)."""

CHEST_CLICKS: tuple[tuple[Click, ...], ...] = (
    ((0, 0, "pickup"), (5, 0, "pickup")),
    ((1, 1, "pickup"), (6, 1, "pickup"), (6, 0, "pickup")),
    ((2, 0, "quick_move"),),
    ((54, 0, "quick_move"),),
    tuple((4, button, "swap") for button in range(9)),
    ((1, 40, "swap"),),
    (
        (27, 0, "pickup"),
        (_OUT, 0, "quick_craft"),
        (7, 1, "quick_craft"),
        (8, 1, "quick_craft"),
        (9, 1, "quick_craft"),
        (_OUT, 2, "quick_craft"),
        (27, 0, "pickup"),
    ),
    (
        (6, 0, "pickup"),
        (_OUT, 4, "quick_craft"),
        (10, 5, "quick_craft"),
        (11, 5, "quick_craft"),
        (_OUT, 6, "quick_craft"),
        (6, 0, "pickup"),
    ),
    ((3, 0, "pickup"), (3, 0, "pickup_all"), (3, 0, "pickup")),
    ((1, 0, "throw"),),
    ((7, 1, "throw"),),
    ((8, 0, "pickup"), (_OUT, 1, "pickup")),
    ((_OUT, 0, "pickup"),),
)
"""The clicks in the chest's menu (0-26 the chest, 27-53 the inventory, 54-62 the hotbar), a
window each: take and put down; half a stack, one, the rest; shift-click from the chest and
from the hotbar; the number keys 1-9; the off-hand key; drag evenly; drag one each; double-click;
Q and Ctrl+Q over a slot; one and then the rest dropped outside the window."""

INVENTORY_CLICKS: tuple[tuple[Click, ...], ...] = (
    ((36, 0, "pickup"), (15, 0, "pickup")),
    ((37, 1, "pickup"), (13, 1, "pickup"), (13, 0, "pickup")),
    ((9, 0, "quick_move"),),
    ((12, 0, "quick_move"),),
    ((11, 0, "quick_move"),),
    ((5, 0, "quick_move"),),
    tuple((14, button, "swap") for button in range(9)),
    ((36, 40, "swap"),),
    (
        (15, 0, "pickup"),
        (_OUT, 0, "quick_craft"),
        (20, 1, "quick_craft"),
        (21, 1, "quick_craft"),
        (22, 1, "quick_craft"),
        (_OUT, 2, "quick_craft"),
        (15, 0, "pickup"),
    ),
    (
        (20, 0, "pickup"),
        (_OUT, 4, "quick_craft"),
        (23, 5, "quick_craft"),
        (24, 5, "quick_craft"),
        (_OUT, 6, "quick_craft"),
        (20, 0, "pickup"),
    ),
    ((21, 0, "pickup"), (21, 0, "pickup_all"), (21, 0, "pickup")),
    ((39, 0, "throw"),),
    ((13, 1, "throw"),),
    ((21, 0, "pickup"), (_OUT, 1, "pickup")),
    ((_OUT, 0, "pickup"),),
)
"""The clicks in the Bot's own inventory menu (5-8 the armor, 9-35 the inventory, 36-44 the
hotbar, 45 the off hand), a window each: as in the chest, with shift-clicks between the
inventory and the hotbar, and a helmet shift-clicked onto the head and back."""


async def _set_kit(context: GroupContext) -> None:
    """Empty the Bot's inventory, then fill it with `KIT`."""
    await context.control.run(f"clear {_CLICKER}")
    for entry in KIT:
        await context.control.run(f"item replace entity {_CLICKER} {entry}")


async def _open_chest(context: GroupContext, bot: Bot) -> None:
    """Open the chest in a window of its own: its menu and the Bot's come with it.

    Raises:
        ValueError: The server opened no container for the Bot. A click meant for the chest
            would land on the Bot's own inventory menu.
    """
    async with context.observe(*CLICK_PACKETS):
        await bot.place(*CHEST, Face.UP)
    if bot.inventory.window_id == 0:
        msg = "the chest did not open: the server sent the Bot no open_screen for it"
        raise ValueError(msg)


async def _close(bot: Bot) -> None:
    """Close the open menu, and wait until the server has: Control acts on another connection."""
    await bot.close_container()
    await bot.sync()


async def _click_windows(
    context: GroupContext, bot: Bot, sequences: tuple[tuple[Click, ...], ...]
) -> None:
    """Click each of `sequences` in a window of its own, then close the menu."""
    for sequence in sequences:
        async with context.observe(*CLICK_PACKETS):
            for slot, button, mode in sequence:
                await bot.click(slot, button, mode)
    await _close(bot)


async def _see_chest(context: GroupContext, bot: Bot) -> None:
    """Open the chest again, to compare what the clicks left in it and in the Bot, then close it."""
    await _open_chest(context, bot)
    await _close(bot)


@group("inventory/clicks-inventory", masks=DROP_MASKS)
async def clicks_inventory(context: GroupContext) -> None:
    """The Bot clicks in every mode in its own inventory menu, with no container open."""
    async with _arena(context, _CLICKER) as bot:
        await _set_kit(context)
        await _click_windows(context, bot, INVENTORY_CLICKS)


@group("inventory/clicks-chest", masks=(*DROP_MASKS, CHEST_PITCH))
async def clicks_chest(context: GroupContext) -> None:
    """The Bot opens a chest, clicks in every mode in its menu, then opens it again."""
    x, y, z = CHEST
    async with _arena(context, _CLICKER) as bot, contextlib.AsyncExitStack() as undo:
        await context.control.run(f"setblock {x} {y} {z} minecraft:air")
        undo.push_async_callback(context.control.run, f"setblock {x} {y} {z} minecraft:air")
        await context.control.run(f"setblock {x} {y} {z} {_CHEST}")
        await _set_kit(context)
        await _open_chest(context, bot)
        await _click_windows(context, bot, CHEST_CLICKS)
        await _see_chest(context, bot)
