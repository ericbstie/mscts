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
menu), and not again through window 0 once it closes. Every menu but the lectern ends with the
27 and the hotbar.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from mscts.codec.registry_names import registry_names
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
_HOTBAR = tuple((True, index) for index in range(9))
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

    `layout` is None for a menu the tracker does not lay out: its slots are `own`, as sent.
    """

    window_id: int
    menu: str | None
    own: list[Stack | None]
    layout: tuple[_Place, ...] | None
    carried: Stack | None = None
    state_id: int = 0


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
