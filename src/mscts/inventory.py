"""The player's inventory and the open container, kept as the 26.3 client keeps them.

`ClientPacketListener` (javap, docs/research/2026-10-04-bot-inventory.md) sends a
`container_set_content` or `container_set_slot` for window 0 to the player's inventory menu,
even with a container open, and one for the open container's id to that container's menu; any
other id changes nothing. `set_cursor_item` sets the open menu's carried stack, and
`set_player_inventory` one index of the player's `Inventory`. `open_screen` makes a new menu
the open one, as `mount_screen_open` does for a horse's or a nautilus's inventory, and the
server's `container_close` goes back to the inventory menu.

A menu's player slots are the player's `Inventory` itself, so a stack set through one menu
shows in every other. That matters: while a menu is open the server sends the player's
inventory changes through that menu's window only (`ServerPlayer.tick` broadcasts the open
menu), and not again through window 0 once it closes. Every menu but the lectern has the 27
and the hotbar after its own slots; the crafter's result comes after them.

A click changes the open menu's slots as `AbstractContainerMenu.doClick` does on the client,
in the inventory menu and the menus of chests, barrels, shulker boxes, dispensers, droppers
and hoppers, and gives the `container_click` that reports it.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from mscts.codec.registry_names import equipment_slots, max_stack_sizes, registry_names
from mscts.entities import Entity
from mscts.net import ProtocolError
from mscts.target import TARGET

PLAYER_INDEXES = 43
"""`Inventory`'s indexes: the hotbar (0 to 8), the rest (9 to 35), the feet, legs, chest and
head (36 to 39), the off hand (40), the body (41) and the saddle (42)."""


def _no_change() -> Mapping[str, object]:
    return {"added": [], "removed": []}


@dataclass(frozen=True, slots=True)
class Stack:
    """A stack of items, as the server last described it.

    Attributes:
        item: Its item's name, e.g. `minecraft:stone`; `#<id>` for an id outside the registry.
        count: How many items it holds, at least 1.
        components: The components it changes from its item's defaults, as the codec decodes
            them: `{"added": [...], "removed": [...]}`.
    """

    item: str
    count: int
    components: Mapping[str, object] = field(default_factory=_no_change)


@dataclass(frozen=True, slots=True)
class Inventory:
    """The player's inventory and the open menu, at one moment (`Bot.inventory`).

    Attributes:
        window_id: The open menu's window id: 0 for the player's own inventory menu.
        menu: The open menu's type, e.g. `minecraft:generic_9x3`; None for the player's own;
            for a mount's inventory, the mount's entity type, e.g. `minecraft:horse`.
        slots: The open menu's slots, by slot number: the numbers a click names. Each is a
            Stack, or None for an empty slot.
        carried: The stack on the cursor, or None.
        state_id: The state id the server last sent for the open menu.
        player: The player's inventory, by `Inventory` index (see `PLAYER_INDEXES`).
    """

    window_id: int
    menu: str | None
    slots: tuple[Stack | None, ...]
    carried: Stack | None
    state_id: int
    player: tuple[Stack | None, ...]


type _Place = tuple[bool, int]
"""Where a menu slot's stack lives: in the player's `Inventory` (True) or the menu's own
container (False), and its index there."""

_STORAGE = tuple((True, index) for index in range(9, 36))
_HOTBAR_SIZE = 9
_HOTBAR = tuple((True, index) for index in range(_HOTBAR_SIZE))
_HEAD, _CHEST, _LEGS, _FEET, _OFF_HAND = 39, 38, 37, 36, 40
_CRAFTING = 5
"""The inventory menu's own container: the crafting result, then the 2x2 grid."""

_INVENTORY_MENU = (
    *((False, index) for index in range(_CRAFTING)),
    *((True, index) for index in (_HEAD, _CHEST, _LEGS, _FEET)),
    *_STORAGE,
    *_HOTBAR,
    (True, _OFF_HAND),
)
"""`InventoryMenu`'s slots: result, crafting grid, armor from the head down, the 27, the hotbar,
then the off hand."""

_CONTAINER_SIZES = {
    "minecraft:generic_9x1": 9,
    "minecraft:generic_9x2": 18,
    "minecraft:generic_9x3": 27,
    "minecraft:generic_9x4": 36,
    "minecraft:generic_9x5": 45,
    "minecraft:generic_9x6": 54,
    "minecraft:generic_3x3": 9,
    "minecraft:anvil": 3,
    "minecraft:beacon": 1,
    "minecraft:blast_furnace": 3,
    "minecraft:brewing_stand": 5,
    "minecraft:cartography_table": 3,
    "minecraft:crafting": 10,
    "minecraft:enchantment": 2,
    "minecraft:furnace": 3,
    "minecraft:grindstone": 3,
    "minecraft:hopper": 5,
    "minecraft:loom": 4,
    "minecraft:merchant": 3,
    "minecraft:shulker_box": 27,
    "minecraft:smithing": 4,
    "minecraft:smoker": 3,
    "minecraft:stonecutter": 2,
}
"""The menus laid out as their own slots, then the 27, then the hotbar, by how many own slots
they have (javap of each menu's constructor: its `addSlot`s, then `addStandardInventorySlots`;
an anvil's and a smithing table's inputs and result through `ItemCombinerMenu`)."""
_CRAFTER, _CRAFTER_GRID = "minecraft:crafter_3x3", 9
"""`CrafterMenu.addSlots`: its 3x3, the 27 and the hotbar, then its result."""
_LECTERN = "minecraft:lectern"
"""`LecternMenu`: one slot, the book, and none of the player's."""
_HORSES = frozenset(
    {
        "minecraft:camel",
        "minecraft:camel_husk",
        "minecraft:donkey",
        "minecraft:horse",
        "minecraft:llama",
        "minecraft:mule",
        "minecraft:skeleton_horse",
        "minecraft:trader_llama",
        "minecraft:zombie_horse",
    }
)
"""The entity types whose class extends `AbstractHorse` (javap): a `HorseInventoryMenu` each."""
_NAUTILUSES = frozenset({"minecraft:nautilus", "minecraft:zombie_nautilus"})
"""The entity types whose class extends `AbstractNautilus`: a `NautilusInventoryMenu` each."""
_MOUNT_EQUIPMENT, _MOUNT_ROWS = 2, 3
"""A mount's menu: its saddle and body slots, then its chest's 3 rows (a horse's only)."""


@dataclass(slots=True)
class _Menu:
    """One menu: its own container's stacks, where each slot lives, its cursor and state id.

    `layout` is None for a menu outside the registry: its slots are `own`, as sent.
    """

    window_id: int
    menu: str | None
    own: list[Stack | None]
    layout: tuple[_Place, ...] | None
    carried: Stack | None = None
    state_id: int = 0
    quickcraft_status: int = 0
    quickcraft_type: int = 0
    quickcraft_slots: set[int] = field(default_factory=set)


def _inventory_menu() -> _Menu:
    return _Menu(window_id=0, menu=None, own=[None] * _CRAFTING, layout=_INVENTORY_MENU)


def _opened(window_id: int, menu: str) -> _Menu:
    """The menu `open_screen` opens: one outside the registry is laid out as sent."""
    if menu == _CRAFTER:
        grid = tuple((False, index) for index in range(_CRAFTER_GRID))
        layout = (*grid, *_STORAGE, *_HOTBAR, (False, _CRAFTER_GRID))
        return _Menu(window_id, menu, [None] * (_CRAFTER_GRID + 1), layout)
    if menu == _LECTERN:
        return _Menu(window_id, menu, [None], ((False, 0),))
    size = _CONTAINER_SIZES.get(menu)
    if size is None:
        return _Menu(window_id=window_id, menu=menu, own=[], layout=None)
    return _laid_out(window_id, menu, size)


def _laid_out(window_id: int, menu: str, size: int) -> _Menu:
    """A menu of `size` own slots, then the 27 and the hotbar."""
    layout = (*((False, index) for index in range(size)), *_STORAGE, *_HOTBAR)
    return _Menu(window_id=window_id, menu=menu, own=[None] * size, layout=layout)


def _mount_menu(fields: Mapping[str, object], entities: Mapping[int, Entity]) -> _Menu | None:
    """The menu a `mount_screen_open` opens for its entity among `entities`, or None for none."""
    mount = entities.get(_int(fields, "entity_id"))
    window_id = _int(fields, "window_id")
    if mount is None:
        return None
    if mount.type in _NAUTILUSES:
        return _laid_out(window_id, mount.type, _MOUNT_EQUIPMENT)
    if mount.type in _HORSES:
        columns = max(_int(fields, "inventory_columns"), 0)
        return _laid_out(window_id, mount.type, _MOUNT_EQUIPMENT + _MOUNT_ROWS * columns)
    return None


class InventoryTracker:
    """Follows the inventory packets a Bot receives, as `ClientPacketListener` does."""

    def __init__(self) -> None:
        """Start as a new player: nothing anywhere, and no container open."""
        self._player: list[Stack | None] = [None] * PLAYER_INDEXES
        self._inventory = _inventory_menu()
        self._open = self._inventory

    def clear(self) -> None:
        """Start again, as the new `LocalPlayer` a login or a respawn brings does."""
        self._player = [None] * PLAYER_INDEXES
        self._inventory = _inventory_menu()
        self._open = self._inventory

    def view(self) -> Inventory:
        """The inventory and the open menu as they are now."""
        menu = self._open
        return Inventory(
            window_id=menu.window_id,
            menu=menu.menu,
            slots=tuple(self._slots(menu)),
            carried=menu.carried,
            state_id=menu.state_id,
            player=tuple(self._player),
        )

    def close(self) -> None:
        """Go back to the player's inventory menu, as `Player.closeContainer` does."""
        self._open = self._inventory

    def remove_from_selected(self, selected: int, *, whole: bool) -> None:
        """Take one item, or the `whole` stack, from hotbar slot `selected`, as the client does."""
        held = self._player[selected]
        if held is None:
            return
        left = 0 if whole else held.count - 1
        self._player[selected] = Stack(held.item, left, held.components) if left else None

    def click(self, slot: int, button: int, mode: str) -> dict[str, object]:
        """Click `slot` of the open menu as the client does; return the `container_click` fields.

        The menu's slots and carried stack change as `doClick` changes them on the client
        (`CLICK_MODES` names the modes). The fields hold the slots whose stacks changed, each
        hashed, in the order the client's `Int2ObjectOpenHashMap` gives them, and the carried
        stack (`MultiPlayerGameMode.handleContainerInput`). The Bot predicts as a survival
        player: a clone, or a drag of a full stack to each slot, changes nothing.

        Raises:
            ValueError: The click cannot be sent as given (an unknown mode, a slot or button
                out of range), or the Bot cannot predict it: a menu other than the inventory's,
                a chest's, a dispenser's, a hopper's or a shulker box's; the crafting result; a
                bundle; a swap that puts the slot's stack elsewhere; or a stack whose components
                change, which it cannot hash. Nothing changes.
        """
        number = CLICK_MODES.get(mode)
        if number is None:
            msg = f"mode must be one of {', '.join(CLICK_MODES)}, not {mode!r}"
            raise ValueError(msg)
        if not (-_SHORT <= slot < _SHORT and -_BYTE <= button < _BYTE):
            msg = f"slot {slot} must fit a Short and button {button} a Byte"
            raise ValueError(msg)
        menu = self._open
        if menu.layout is None or menu.menu not in _CLICK_MENUS:
            msg = f"the Bot does not predict a click in a {menu.menu} menu"
            raise ValueError(msg)
        if menu.window_id == 0 and slot == _RESULT:
            msg = "the Bot does not predict a click on the crafting result"
            raise ValueError(msg)
        saved = (list(self._player), list(menu.own), menu.carried, menu.quickcraft_status)
        saved_drag = (menu.quickcraft_type, set(menu.quickcraft_slots))
        before = self._slots(menu)
        try:
            _Click(self._player, menu, menu.layout).run(slot, button, number)
            after = self._slots(menu)
            differ = [
                index
                for index, (old, new) in enumerate(zip(before, after, strict=True))
                if old != new
            ]
            changed = [
                {"slot": index, "item": _hashed(after[index])} for index in _hash_map_order(differ)
            ]
            carried = _hashed(menu.carried)
        except ValueError:
            self._player[:], menu.own[:], menu.carried, menu.quickcraft_status = saved
            menu.quickcraft_type, menu.quickcraft_slots = saved_drag
            raise
        return {
            "window_id": menu.window_id,
            "state_id": menu.state_id,
            "slot": slot,
            "button": button,
            "mode": number,
            "changed_slots": changed,
            "carried_item": carried,
        }

    def follow(
        self, name: str, fields: Mapping[str, object], entities: Mapping[int, Entity] | None = None
    ) -> None:
        """Apply one clientbound play packet's decoded `fields`; other packets change nothing.

        `entities` are the entities the Bot knows of: `mount_screen_open` opens a menu only for
        a horse or a nautilus among them (`handleMountScreenOpen`).
        """
        match name:
            case "minecraft:open_screen":
                menu = _menu_name(_int(fields, "window_type"))
                self._open = _opened(_int(fields, "window_id"), menu)
            case "minecraft:mount_screen_open":
                self._open_mount(fields, entities)
            case "minecraft:container_close":
                self.close()
            case "minecraft:set_cursor_item":
                self._open.carried = _stack(fields.get("slot_data"))
            case "minecraft:set_player_inventory":
                self._set_player(_int(fields, "slot"), _stack(fields.get("slot_data")))
            case "minecraft:container_set_slot":
                menu = self._addressed(_int(fields, "window_id"))
                value = _stack(fields.get("slot_data"))
                if menu is not None and self._set(menu, _int(fields, "slot"), value):
                    menu.state_id = _int(fields, "state_id")
            case "minecraft:container_set_content":
                menu = self._addressed(_int(fields, "window_id"))
                if menu is not None:
                    self._fill(menu, fields)
            case _:
                pass

    def _set_player(self, index: int, value: Stack | None) -> None:
        """`Inventory.setItem` at `index`; an index it lacks changes nothing."""
        if 0 <= index < PLAYER_INDEXES:
            self._player[index] = value

    def _open_mount(
        self, fields: Mapping[str, object], entities: Mapping[int, Entity] | None
    ) -> None:
        """Open the mount's menu a `mount_screen_open` names, if it is a known mount."""
        opened = _mount_menu(fields, entities or {})
        if opened is not None:
            self._open = opened

    def _addressed(self, window_id: int) -> _Menu | None:
        """The menu a set packet for `window_id` goes to, or None (`handleContainerSetSlot`)."""
        if window_id == 0:
            return self._inventory
        return self._open if window_id == self._open.window_id else None

    def _fill(self, menu: _Menu, fields: Mapping[str, object]) -> None:
        """`initializeContents`: each slot sent, then the carried stack, then the state id."""
        stacks = [_stack(value) for value in _get(fields, "slot_data", list)]
        if menu.layout is None:
            menu.own = stacks
        else:
            for index, value in enumerate(stacks):
                self._set(menu, index, value)
        menu.carried = _stack(fields.get("carried_item"))
        menu.state_id = _int(fields, "state_id")

    def _set(self, menu: _Menu, index: int, value: Stack | None) -> bool:
        """Set slot `index` of `menu`, if it has one: whether it had."""
        places = menu.layout
        count = len(menu.own) if places is None else len(places)
        if not 0 <= index < count:
            return False
        in_player, at = (False, index) if places is None else places[index]
        (self._player if in_player else menu.own)[at] = value
        return True

    def _slots(self, menu: _Menu) -> list[Stack | None]:
        if menu.layout is None:
            return list(menu.own)
        return [(self._player if in_player else menu.own)[at] for in_player, at in menu.layout]


def _stack(value: object) -> Stack | None:
    """A decoded `SLOT` value as a Stack: None stays None."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        msg = f"expected a stack, got {value!r}"
        raise ProtocolError(msg)
    fields = cast("Mapping[str, object]", value)
    item = _name("minecraft:item", _int(fields, "item"))
    return Stack(item, _int(fields, "count"), _get(fields, "components", Mapping))


def _menu_name(menu_id: int) -> str:
    return _name("minecraft:menu", menu_id)


def _name(registry: str, entry: int) -> str:
    names = registry_names(TARGET.minecraft_version, registry)
    return names[entry] if 0 <= entry < len(names) else f"#{entry}"


def _get[T](fields: Mapping[str, object], name: str, kind: type[T]) -> T:
    """`fields[name]`, which the packet's schema guarantees is a `kind`."""
    value = fields.get(name)
    if not isinstance(value, kind):
        msg = f"expected a {kind.__name__} {name}, got {value!r}"
        raise ProtocolError(msg)
    return value


def _int(fields: Mapping[str, object], name: str) -> int:
    return _get(fields, name, int)


# Clicks: `AbstractContainerMenu.doClick` and the menus' `quickMoveStack` (26.3, javap).

CLICK_MODES = MappingProxyType(
    {
        "pickup": 0,
        "quick_move": 1,
        "swap": 2,
        "clone": 3,
        "throw": 4,
        "quick_craft": 5,
        "pickup_all": 6,
    }
)
"""`ContainerInput`'s ids, by the name `Bot.click` takes."""

_PICKUP, _QUICK_MOVE, _SWAP, _CLONE, _THROW, _QUICK_CRAFT, _PICKUP_ALL = range(7)
OUTSIDE = -999
"""The slot a click outside the menu names (`AbstractContainerScreen`): it drops the cursor's."""
_CLICK_MENUS = frozenset(
    {
        None,  # the player's inventory menu
        "minecraft:generic_9x1",
        "minecraft:generic_9x2",
        "minecraft:generic_9x3",
        "minecraft:generic_9x4",
        "minecraft:generic_9x5",
        "minecraft:generic_9x6",
        "minecraft:generic_3x3",
        "minecraft:hopper",
        "minecraft:shulker_box",
    }
)
"""The menus whose `quickMoveStack` and slot rules the Bot predicts: `InventoryMenu`, `ChestMenu`,
`DispenserMenu`, `HopperMenu` and `ShulkerBoxMenu`."""
_OFF_HAND_BUTTON = 40
"""The swap button for the off hand (the F key): `Inventory` index 40."""
_CONTAINER_MAX = 99
"""`Container.getMaxStackSize`: no container the Bot lays out lowers it."""
_DEFAULT_STACK = 64
_ARMOR = {5: "head", 6: "chest", 7: "legs", 8: "feet"}
"""The inventory menu's armor slots (`ArmorSlot`): each takes only its own slot's items, one."""
_ARMOR_SLOT_OF = {"head": 5, "chest": 6, "legs": 7, "feet": 8}
"""Where `InventoryMenu.quickMoveStack` moves a humanoid armor item: 8 - its slot's index."""
_INVENTORY_STORAGE = 9
"""The inventory menu's first slot of the 27; the crafting grid and the armor come before."""
_INVENTORY_OFF_HAND = 45
_INVENTORY_HOTBAR = 36
_INVENTORY_END = 45
_RESULT = 0
_SHORT, _BYTE = 1 << 15, 1 << 7
_MAX_CHANGED = 128


class _UnpredictableError(ValueError):
    """A click whose result the Bot cannot predict as the client does: nothing is sent."""


class _Click:
    """One click on one menu laid out by the tracker, changing the tracker's stacks in place."""

    def __init__(self, player: list[Stack | None], menu: _Menu, places: tuple[_Place, ...]) -> None:
        self.player = player
        self.menu = menu
        self.places = places
        self.size = len(places)
        self.is_inventory = menu.window_id == 0
        self.shulker = menu.menu == "minecraft:shulker_box"
        self.own_size = len(menu.own)

    def get(self, index: int) -> Stack | None:
        in_player, at = self.places[index]
        return (self.player if in_player else self.menu.own)[at]

    def put(self, index: int, value: Stack | None) -> None:
        in_player, at = self.places[index]
        (self.player if in_player else self.menu.own)[at] = value

    @property
    def carried(self) -> Stack | None:
        return self.menu.carried

    @carried.setter
    def carried(self, value: Stack | None) -> None:
        self.menu.carried = value

    def slot_max(self, index: int, stack: Stack) -> int:
        """`Slot.getMaxStackSize(stack)`: the container's limit or the item's, whichever is less."""
        limit = 1 if self.is_inventory and index in _ARMOR else _CONTAINER_MAX
        return min(limit, _max_stack_size(stack))

    def may_place(self, index: int, stack: Stack) -> bool:
        """`Slot.mayPlace`: armor slots take their own slot's items; a shulker box no box."""
        if self.is_inventory and index == _RESULT:
            return False
        if self.is_inventory and index in _ARMOR:
            return _equipment_slot(stack) == _ARMOR[index]
        if self.shulker and index < self.own_size:
            return not stack.item.endswith("shulker_box")
        return True

    def can_take_for_pick_all(self, index: int) -> bool:
        """`canTakeItemForPickAll`: the inventory menu never takes from its crafting result."""
        return not (self.is_inventory and index == _RESULT)

    def run(self, slot: int, button: int, mode: int) -> None:
        """`doClick`."""
        menu = self.menu
        if mode == _QUICK_CRAFT:
            self.quick_craft(slot, button)
        elif menu.quickcraft_status != 0:
            self.reset_quick_craft()
        elif mode in {_PICKUP, _QUICK_MOVE} and button in {0, 1}:
            self.pickup_or_quick_move(slot, button, mode)
        elif mode == _SWAP and (0 <= button < _HOTBAR_SIZE or button == _OFF_HAND_BUTTON):
            self.swap(slot, button)
        elif mode == _THROW and self.carried is None and slot >= 0:
            self.throw(slot, button)
        elif mode == _PICKUP_ALL and slot >= 0:
            self.pickup_all(slot, button)
        # CLONE copies a stack only with infinite materials (creative): the Bot predicts survival.

    def reset_quick_craft(self) -> None:
        self.menu.quickcraft_status = 0
        self.menu.quickcraft_slots.clear()

    def quick_craft(self, slot: int, button: int) -> None:
        """A drag: start (header 0), add a slot (1), end (2); a type in bits 2-3."""
        menu = self.menu
        before = menu.quickcraft_status
        menu.quickcraft_status = button & 3
        status = menu.quickcraft_status
        carried = self.carried
        if ((before != 1 or status != 2) and before != status) or carried is None:  # noqa: PLR2004 - the end header
            self.reset_quick_craft()
        elif status == 0:
            menu.quickcraft_type = (button >> 2) & 3
            if menu.quickcraft_type in {0, 1}:  # 2, a stack each, needs infinite materials
                menu.quickcraft_status = 1
                menu.quickcraft_slots.clear()
            else:
                self.reset_quick_craft()
        elif status == 1:
            self._require_slot(slot)
            if self.drags_to(slot, carried, len(menu.quickcraft_slots), strictly=True):
                menu.quickcraft_slots.add(slot)
        elif status == 2:  # noqa: PLR2004 - the end header
            self.end_quick_craft(carried)
        else:
            self.reset_quick_craft()

    def drags_to(self, index: int, carried: Stack, slots: int, *, strictly: bool) -> bool:
        """Whether a drag of `carried` takes in slot `index`, `slots` slots being in the drag."""
        enough = carried.count > slots if strictly else carried.count >= slots
        return (
            self.quick_replaces(index, carried)
            and self.may_place(index, carried)
            and (self.menu.quickcraft_type == 2 or enough)  # noqa: PLR2004 - a stack each
        )

    def quick_replaces(self, index: int, stack: Stack) -> bool:
        """`canItemQuickReplace(slot, stack, true)`: empty, or the same stack with room."""
        held = self.get(index)
        if held is None:
            return True
        return _same_stack(held, stack) and held.count <= _max_stack_size(stack)

    def end_quick_craft(self, carried: Stack) -> None:
        menu = self.menu
        slots = set(menu.quickcraft_slots)
        if not slots:
            self.reset_quick_craft()
            return
        if len(slots) == 1:
            (only,) = slots
            self.reset_quick_craft()
            self.run(only, menu.quickcraft_type, _PICKUP)
            return
        remaining = carried.count
        for index in slots:  # each slot's share does not depend on the order
            if not self.drags_to(index, carried, len(slots), strictly=False):
                continue
            held = self.get(index)
            already = 0 if held is None else held.count
            limit = min(_max_stack_size(carried), self.slot_max(index, carried))
            share = carried.count // len(slots) if menu.quickcraft_type == 0 else 1
            placed = min(share + already, limit)
            remaining -= placed - already
            self.put(index, _counted(carried, placed))
        self.carried = _counted(carried, remaining)
        self.reset_quick_craft()

    def pickup_or_quick_move(self, slot: int, button: int, mode: int) -> None:
        primary = button == 0
        carried = self.carried
        if slot == OUTSIDE:
            if carried is not None:  # dropped: all, or one
                self.carried = None if primary else _counted(carried, carried.count - 1)
            return
        if slot < 0:
            return
        self._require_slot(slot)
        if mode == _QUICK_MOVE:
            result = self.quick_move(slot)
            while result is not None and _same_item(self.get(slot), result):
                result = self.quick_move(slot)
            return
        self.pickup(slot, primary=primary)

    def pickup(self, slot: int, *, primary: bool) -> None:
        """A left (primary) or right click on a slot."""
        held, carried = self.get(slot), self.carried
        for stack in (held, carried):
            if stack is not None and _is_bundle(stack):
                msg = f"the Bot does not predict a click with a bundle ({stack.item})"
                raise _UnpredictableError(msg)
        if held is None:
            if carried is not None:
                self.carried = self.safe_insert(slot, carried, carried.count if primary else 1)
        elif carried is None:
            taken = self.try_remove(slot, held.count if primary else (held.count + 1) // 2, None)
            if taken is not None:
                self.carried = taken
        else:
            self.pickup_onto(slot, held, carried, primary=primary)

    def pickup_onto(self, slot: int, held: Stack, carried: Stack, *, primary: bool) -> None:
        """A click with a stack on the cursor on a slot that holds one: merge, swap or take."""
        if self.may_place(slot, carried):
            if _same_stack(held, carried):
                self.carried = self.safe_insert(slot, carried, carried.count if primary else 1)
            elif carried.count <= self.slot_max(slot, carried):
                self.carried = held
                self.put(slot, carried)
        elif _same_stack(held, carried):
            taken = self.try_remove(slot, held.count, _max_stack_size(carried) - carried.count)
            if taken is not None:
                self.carried = _counted(carried, carried.count + taken.count)

    def safe_insert(self, index: int, stack: Stack, count: int) -> Stack | None:
        """`Slot.safeInsert`: put up to `count` of `stack` in the slot; return what is left."""
        if not self.may_place(index, stack):
            return stack
        held = self.get(index)
        already = 0 if held is None else held.count
        moved = min(count, stack.count, self.slot_max(index, stack) - already)
        if moved <= 0:
            return stack
        if held is None:
            self.put(index, _counted(stack, moved))
        elif _same_stack(held, stack):
            self.put(index, _counted(held, already + moved))
        else:
            return stack
        return _counted(stack, stack.count - moved)

    def try_remove(self, index: int, count: int, limit: int | None) -> Stack | None:
        """`Slot.tryRemove`: up to `count` (and `limit`, if given) taken from the slot, or None.

        A slot whose stack it may not put back (`allowModification`) gives only its whole stack.
        """
        held = self.get(index)
        if held is None:
            return None
        ceiling = held.count if limit is None else limit
        if not self.may_place(index, held) and ceiling < held.count:
            return None
        taken = min(count, ceiling)
        if taken <= 0:
            return None
        taken = min(taken, held.count)
        self.put(index, _counted(held, held.count - taken))
        return _counted(held, taken)

    def quick_move(self, slot: int) -> Stack | None:
        """`quickMoveStack`: the stack as it was if any of it moved, else None."""
        held = self.get(slot)
        if held is None:
            return None
        start, end, backwards = (
            self.inventory_target(slot, held) if self.is_inventory else self.chest_target(slot)
        )
        left, moved = self.move_to(held, held.count, start, end, backwards=backwards)
        if not moved:
            return None
        self.put(slot, _counted(held, left))
        return held

    def chest_target(self, slot: int) -> tuple[int, int, bool]:
        """`ChestMenu` and the like: a container slot to the player's, from the end; else back."""
        if slot < self.own_size:
            return (self.own_size, self.size, True)
        return (0, self.own_size, False)

    def inventory_target(self, slot: int, held: Stack) -> tuple[int, int, bool]:
        """`InventoryMenu.quickMoveStack`'s choice of the slots a slot's stack goes to.

        The crafting grid and the armor go to the 27 and the hotbar; an armor item to its empty
        armor slot, an off-hand item to the empty off hand; else the 27 to the hotbar and back.
        """
        equipment = _equipment_slot(held)
        armor = _ARMOR_SLOT_OF.get(equipment) if equipment is not None else None
        if slot < _INVENTORY_STORAGE:
            return (_INVENTORY_STORAGE, _INVENTORY_END, False)
        if armor is not None and self.get(armor) is None:
            return (armor, armor + 1, False)
        if equipment == "offhand" and self.get(_INVENTORY_OFF_HAND) is None:
            return (_INVENTORY_OFF_HAND, _INVENTORY_OFF_HAND + 1, False)
        if slot < _INVENTORY_HOTBAR:
            return (_INVENTORY_HOTBAR, _INVENTORY_END, False)
        if slot < _INVENTORY_END:
            return (_INVENTORY_STORAGE, _INVENTORY_HOTBAR, False)
        return (_INVENTORY_STORAGE, _INVENTORY_END, False)

    def move_to(
        self, stack: Stack, count: int, start: int, end: int, *, backwards: bool
    ) -> tuple[int, bool]:
        """`moveItemStackTo`: merge into matching stacks, then into the first empty slot.

        Returns how many of `count` are left, and whether any moved.
        """
        moved = False
        order = range(end - 1, start - 1, -1) if backwards else range(start, end)
        if _max_stack_size(stack) > 1:
            for index in order:
                if count == 0:
                    break
                held = self.get(index)
                if held is None or not _same_stack(stack, held):
                    continue
                limit = self.slot_max(index, held)
                if held.count + count <= limit:
                    self.put(index, _counted(held, held.count + count))
                    count, moved = 0, True
                elif held.count < limit:
                    count -= limit - held.count
                    self.put(index, _counted(held, limit))
                    moved = True
        if count > 0:
            for index in order:
                if self.get(index) is None and self.may_place(index, stack):
                    placed = min(count, self.slot_max(index, stack))
                    self.put(index, _counted(stack, placed))
                    count -= placed
                    moved = True
                    break
        return count, moved

    def swap(self, slot: int, button: int) -> None:
        """A number key (or F, button 40) over a slot: swap it with that `Inventory` index."""
        self._require_slot(slot)
        theirs, held = self.player[button], self.get(slot)
        if theirs is None and held is None:
            return
        if theirs is None:
            self.player[button] = held
            self.put(slot, None)
        elif held is None:
            if not self.may_place(slot, theirs):
                return
            limit = self.slot_max(slot, theirs)
            if theirs.count > limit:
                self.put(slot, _counted(theirs, limit))
                self.player[button] = _counted(theirs, theirs.count - limit)
            else:
                self.player[button] = None
                self.put(slot, theirs)
        elif self.may_place(slot, theirs):
            if theirs.count > self.slot_max(slot, theirs):
                msg = "the Bot does not predict a swap that puts the slot's stack back elsewhere"
                raise _UnpredictableError(msg)
            self.player[button] = held
            self.put(slot, theirs)

    def throw(self, slot: int, button: int) -> None:
        """Q over a slot: drop one (button 0), or the stack (Ctrl, button 1, repeated)."""
        self._require_slot(slot)
        held = self.get(slot)
        count = 1 if button == 0 else (0 if held is None else held.count)
        taken = self.try_remove(slot, count, None)
        while button == 1 and taken is not None and _same_item(self.get(slot), taken):
            taken = self.try_remove(slot, count, None)

    def pickup_all(self, slot: int, button: int) -> None:
        """A double click: gather the carried stack's kind from the menu, full stacks last."""
        self._require_slot(slot)
        carried = self.carried
        held = self.get(slot)
        if carried is None or held is not None:
            return
        order = range(self.size) if button == 0 else range(self.size - 1, -1, -1)
        for full_stacks in (False, True):
            for index in order:
                carried = self.carried
                if carried is None or carried.count >= _max_stack_size(carried):
                    break
                other = self.get(index)
                if (
                    other is None
                    or not self.quick_replaces(index, carried)
                    or not self.can_take_for_pick_all(index)
                    or (not full_stacks and other.count == _max_stack_size(other))
                ):
                    continue
                taken = self.try_remove(
                    index, other.count, _max_stack_size(carried) - carried.count
                )
                if taken is not None:
                    self.carried = _counted(carried, carried.count + taken.count)

    def _require_slot(self, slot: int) -> None:
        if not 0 <= slot < self.size:
            msg = f"slot {slot} is not one of the menu's {self.size} slots"
            raise ValueError(msg)


def _max_stack_size(stack: Stack) -> int:
    """`ItemStack.getMaxStackSize` for an item's default components."""
    return max_stack_sizes(TARGET.minecraft_version).get(stack.item, _DEFAULT_STACK)


def _equipment_slot(stack: Stack) -> str | None:
    return equipment_slots(TARGET.minecraft_version).get(stack.item)


def _is_bundle(stack: Stack) -> bool:
    """Whether the item is a bundle (`BundleItem` overrides a click on or with it)."""
    name = stack.item.removeprefix("minecraft:")
    return name == "bundle" or name.endswith("_bundle")


def _same_item(stack: Stack | None, other: Stack) -> bool:
    """`ItemStack.isSameItem`."""
    return stack is not None and stack.item == other.item


def _same_stack(stack: Stack, other: Stack) -> bool:
    """`ItemStack.isSameItemSameComponents`."""
    return stack.item == other.item and stack.components == other.components


def _counted(stack: Stack, count: int) -> Stack | None:
    """`stack` with `count` items; None for none."""
    return Stack(stack.item, count, stack.components) if count > 0 else None


def _hashed(stack: Stack | None) -> dict[str, object] | None:
    """`HashedStack.create`: the stack as a `HASHED_SLOT` value.

    Raises:
        _UnpredictableError: The stack changes a component: its hash needs the component's encoding.
    """
    if stack is None:
        return None
    if stack.components != _no_change():
        msg = f"the Bot cannot hash a stack whose components change ({stack.item})"
        raise _UnpredictableError(msg)
    return {"item": _item_id(stack.item), "count": stack.count, "components": _no_change()}


def _item_id(name: str) -> int:
    if name.startswith("#"):
        return int(name[1:])
    return registry_names(TARGET.minecraft_version, "minecraft:item").index(name)


def _mix(key: int) -> int:
    """`HashCommon.mix`: the key times the golden ratio, its high half folded into the low."""
    h = (key * 0x9E3779B9) & 0xFFFFFFFF
    return h ^ (h >> 16)


def _hash_map_order(keys: list[int]) -> list[int]:
    """The order an `Int2ObjectOpenHashMap()` given `keys` in turn iterates them (fastutil).

    Open addressing with linear probing in a table of 32, doubled past three quarters full;
    key 0 is kept apart and comes first, then the table from its last position down.
    """
    size, table, has_zero = 32, [0] * 32, False
    for count, key in enumerate(keys, start=1):
        if key == 0:
            has_zero = True
        else:
            _place(table, key)
        if count - 1 >= min(math.ceil(len(table) * 0.75), len(table) - 1):
            size = max(2, 1 << math.ceil(math.log2(math.ceil((count + 1) / 0.75))))
            grown = [0] * size
            for old in reversed(table):
                if old:
                    _place(grown, old)
            table = grown
    return [0] * has_zero + [key for key in reversed(table) if key]


def _place(table: list[int], key: int) -> None:
    mask = len(table) - 1
    position = _mix(key) & mask
    while table[position]:
        position = (position + 1) & mask
    table[position] = key
