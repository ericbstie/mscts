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

from mscts.bot import Bot
from mscts.compare import Mask
from mscts.group import GroupContext, GroupKind, group
from mscts.groups._world import CONTROL_AT, SPAWN_AT, join_at_spawn, pin_joins
from mscts.spec import CONTROL_PLAYER

_ITEMS = "@e[type=minecraft:item,x=0.5,y=-60,z=0.5,distance=..20"
"""The start of the selector of the items within 20 blocks of the spawn, without its `]`."""

_BEFORE = "mscts_inventory_before"
"""The tag an item already there carries while a Group plays."""

_KILL_NEW_ITEMS = f"kill {_ITEMS},tag=!{_BEFORE}]"

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
        await control.run(f"tag {_ITEMS}] add {_BEFORE}")
        undo.push_async_callback(control.run, f"tag {_ITEMS}] remove {_BEFORE}")
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
    "minecraft:sound",
)
"""The packets a give window compares: the inventory, the item that appears, and the sound."""

_SEVERAL_ITEMS_PACKETS = tuple(name for name in GIVE_PACKETS if name != "minecraft:set_entity_data")
"""What a window that makes several items compares. Vanilla sends each new item's data again at
the end of the tick, in the hash order of its entity id (`ChunkMap.tick` over `entityMap`), and
two servers can number their entities differently. Each item's type is in the slot it fills."""


@dataclass(frozen=True, slots=True)
class _Give:
    """One `/give`: the item and the count, into an empty inventory or a `full` one.

    `stacks` is how many stacks the count makes: `GiveCommand.giveItem` gives a stack at a time,
    and each stack makes an item entity of its own.
    """

    item: str
    count: int
    full: bool = False
    stacks: int = 1

    def packets(self) -> tuple[str, ...]:
        """What the give's window compares."""
        return GIVE_PACKETS if self.stacks == 1 else _SEVERAL_ITEMS_PACKETS


_FULL = f"give {_GIVER} minecraft:dirt 2304"
"""Fills the 36 slots of the Bot's inventory with stacks of 64 dirt (the off hand stays empty)."""

GIVES = (
    _Give("minecraft:stone", 1),
    _Give("minecraft:stone", 64),
    _Give("minecraft:stone", 100, stacks=2),
    _Give("minecraft:diamond_sword", 1),
    _Give("minecraft:stone", 1, full=True),
)
"""The gives, one window each: one stack, a full stack, more than a stack, an unstackable item,
and an item that does not fit, which drops."""


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
                await context.step(case.ticks)
