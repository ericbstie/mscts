"""The Bot's inventory: what the server says is in each slot, kept as the 26.3 client keeps it.

`ClientPacketListener` (26.3 client, javap): `container_set_content` and `container_set_slot`
for window 0 go to the player's inventory menu, even with a container open, and for the open
container's id to its menu; any other id changes nothing. `set_cursor_item` sets the open
menu's carried stack, `set_player_inventory` an inventory index. A menu's player slots are the
player's `Inventory`, so a change through one shows in every menu.
"""

import dataclasses
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TYPE_CHECKING

import pytest

from mscts.bot import Bot, Replies
from mscts.codec.packets import State
from mscts.codec.registry_names import registry_names
from mscts.entities import Entity
from mscts.inventory import (
    CLICK_MODES,
    OUTSIDE,
    Inventory,
    InventoryTracker,
    Stack,
    _hash_map_order,
)
from mscts.net import ProtocolError
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import with_bot
from tests.net.test_bot_entities import added, entity_server
from tests.net.test_bot_move import CODEC, LOGIN, RESPAWN, TICK_END
from tests.net.test_bot_replies import answers, arrived

if TYPE_CHECKING:
    from mscts.codec.packets import Packet

STONE, SWORD = 1, 1050
"""`minecraft:stone` and `minecraft:diamond_sword` in `minecraft:item` (registries report)."""
GENERIC_9X3, FURNACE = 2, 14
"""`minecraft:generic_9x3` and `minecraft:furnace` in `minecraft:menu`."""
CHEST = 3
"""The window id the server gave the open chest."""
CHEST_TITLE = bytes([0x08, 0x00, 0x05]) + b"Chest"  # a network NBT String tag


def slot(item: int, count: int) -> dict[str, object]:
    """A `SLOT` value as the codec decodes it: no component changed."""
    return {"count": count, "item": item, "components": {"added": [], "removed": []}}


def stack(name: str, count: int) -> Stack:
    return Stack(item=f"minecraft:{name}", count=count)


type Received = tuple[str, Mapping[str, object]]


def content(
    window_id: int,
    slots: list[dict[str, object] | None],
    state_id: int = 1,
    carried: dict[str, object] | None = None,
) -> Received:
    fields = {"window_id": window_id, "state_id": state_id, "slot_data": slots}
    return ("minecraft:container_set_content", {**fields, "carried_item": carried})


def set_slot(
    window_id: int, index: int, value: dict[str, object] | None, state_id: int = 2
) -> Received:
    fields = {"window_id": window_id, "state_id": state_id, "slot": index, "slot_data": value}
    return ("minecraft:container_set_slot", fields)


def open_screen(window_id: int, window_type: int) -> Received:
    fields = {"window_id": window_id, "window_type": window_type, "window_title": CHEST_TITLE}
    return ("minecraft:open_screen", fields)


def cursor(value: dict[str, object] | None) -> Received:
    return ("minecraft:set_cursor_item", {"slot_data": value})


def player_slot(index: int, value: dict[str, object] | None) -> Received:
    return ("minecraft:set_player_inventory", {"slot": index, "slot_data": value})


CLOSE = ("minecraft:container_close", {"window_id": CHEST})


def followed(*packets: Received) -> InventoryTracker:
    tracker = InventoryTracker()
    for name, fields in packets:
        tracker.follow(name, fields)
    return tracker


def test_a_fresh_player_holds_nothing_in_its_own_inventory_menu() -> None:
    # InventoryMenu: the crafting result, 4 crafting slots, 4 armor slots, 27 slots, the
    # hotbar's 9 and the off hand: 46, all empty, state id 0. The Inventory has 43 indexes.
    view = InventoryTracker().view()
    assert view == Inventory(
        window_id=0, menu=None, slots=(None,) * 46, carried=None, state_id=0, player=(None,) * 43
    )


def test_the_inventory_menus_contents_fill_the_players_inventory() -> None:
    # Menu slot 36 is hotbar index 0, slot 5 the head (index 39), slot 8 the feet (36), slot 9
    # index 9, slot 45 the off hand (40); slot 1 is the crafting grid, not the Inventory.
    slots: list[dict[str, object] | None] = [None] * 46
    slots[1], slots[5], slots[8] = slot(STONE, 1), slot(STONE, 2), slot(STONE, 3)
    slots[9], slots[36], slots[45] = slot(STONE, 4), slot(SWORD, 1), slot(STONE, 5)
    view = followed(content(0, slots, state_id=7)).view()
    assert view.state_id == 7
    assert view.slots[1] == stack("stone", 1)
    assert view.slots[36] == stack("diamond_sword", 1)
    player = dict(enumerate(view.player))
    assert {index: value for index, value in player.items() if value is not None} == {
        0: stack("diamond_sword", 1),
        9: stack("stone", 4),
        36: stack("stone", 3),
        39: stack("stone", 2),
        40: stack("stone", 5),
    }


def test_the_contents_carried_stack_is_the_menus() -> None:
    tracker = followed(content(0, [None] * 46, carried=slot(STONE, 3)))
    assert tracker.view().carried == stack("stone", 3)


def test_a_player_inventory_slot_shows_in_the_inventory_menu() -> None:
    view = followed(player_slot(0, slot(STONE, 64)), player_slot(40, slot(SWORD, 1))).view()
    assert view.slots[36] == stack("stone", 64)
    assert view.slots[45] == stack("diamond_sword", 1)
    assert view.player[0] == stack("stone", 64)


@pytest.mark.parametrize("index", [-1, 43])
def test_a_player_inventory_index_out_of_range_changes_nothing(index: int) -> None:
    assert followed(player_slot(index, slot(STONE, 1))).view() == InventoryTracker().view()


def test_an_opened_chest_shows_its_slots_then_the_players() -> None:
    # ChestMenu: 9 x rows container slots, then Inventory 9 to 35, then the hotbar, 0 to 8.
    tracker = followed(player_slot(0, slot(STONE, 64)), player_slot(9, slot(SWORD, 1)))
    tracker.follow(*open_screen(CHEST, GENERIC_9X3))
    view = tracker.view()
    assert (view.window_id, view.menu, view.state_id, view.carried) == (
        CHEST,
        "minecraft:generic_9x3",
        0,
        None,
    )
    assert len(view.slots) == 63
    assert view.slots[27] == stack("diamond_sword", 1)
    assert view.slots[54] == stack("stone", 64)
    assert view.slots[:27] == (None,) * 27


def test_the_chests_contents_set_its_slots_and_the_players() -> None:
    slots: list[dict[str, object] | None] = [None] * 63
    slots[0], slots[62] = slot(STONE, 10), slot(SWORD, 1)
    view = followed(open_screen(CHEST, GENERIC_9X3), content(CHEST, slots, state_id=4)).view()
    assert (view.slots[0], view.state_id) == (stack("stone", 10), 4)
    assert view.player[8] == stack("diamond_sword", 1)


def test_a_slot_set_in_the_chest_shows_in_the_inventory_once_it_closes() -> None:
    tracker = followed(open_screen(CHEST, GENERIC_9X3), set_slot(CHEST, 54, slot(STONE, 64)))
    assert tracker.view().state_id == 2
    tracker.follow(*CLOSE)
    view = tracker.view()
    assert (view.window_id, view.menu, len(view.slots)) == (0, None, 46)
    assert view.slots[36] == stack("stone", 64)


def test_a_slot_set_for_window_0_with_a_chest_open_changes_the_players_inventory() -> None:
    # handleContainerSetSlot sends window 0 to the inventory menu whatever is open.
    tracker = followed(open_screen(CHEST, GENERIC_9X3), set_slot(0, 36, slot(STONE, 5)))
    view = tracker.view()
    assert (view.slots[54], view.state_id) == (stack("stone", 5), 0)


@pytest.mark.parametrize(
    "packet",
    [set_slot(5, 0, slot(STONE, 1)), set_slot(CHEST, 63, slot(STONE, 1)), content(5, [None])],
    ids=["another-window", "past-the-last-slot", "contents-of-another-window"],
)
def test_a_slot_the_open_menu_does_not_have_changes_nothing(
    packet: Received,
) -> None:
    before = followed(open_screen(CHEST, GENERIC_9X3)).view()
    assert followed(open_screen(CHEST, GENERIC_9X3), packet).view() == before


def test_the_cursor_is_the_open_menus_and_the_inventory_menu_keeps_its_own() -> None:
    tracker = followed(open_screen(CHEST, GENERIC_9X3), cursor(slot(STONE, 3)))
    assert tracker.view().carried == stack("stone", 3)
    tracker.follow(*CLOSE)
    assert tracker.view().carried is None


def test_a_furnaces_player_slots_are_the_players_inventory() -> None:
    # ServerPlayer.tick broadcasts only the open menu, so a /give with a furnace open arrives
    # at the furnace's slot 30 (its 3, then the 27): the hotbar's first slot, shown once closed.
    tracker = followed(open_screen(CHEST, FURNACE), set_slot(CHEST, 30, slot(STONE, 5)), CLOSE)
    view = tracker.view()
    assert (view.player[0], view.slots[36]) == (stack("stone", 5), stack("stone", 5))


MENU_SLOTS = {
    "generic_9x1": 9,
    "generic_9x2": 18,
    "generic_9x3": 27,
    "generic_9x4": 36,
    "generic_9x5": 45,
    "generic_9x6": 54,
    "generic_3x3": 9,
    "anvil": 3,
    "beacon": 1,
    "blast_furnace": 3,
    "brewing_stand": 5,
    "crafting": 10,
    "enchantment": 2,
    "furnace": 3,
    "grindstone": 3,
    "hopper": 5,
    "loom": 4,
    "merchant": 3,
    "shulker_box": 27,
    "smithing": 4,
    "smoker": 3,
    "cartography_table": 3,
    "stonecutter": 2,
}
"""Each menu's own slots before the player's 27 and hotbar (javap of each menu's constructor:
its `addSlot`s, then `addStandardInventorySlots`)."""


def menu_id(name: str) -> int:
    return registry_names(TARGET.minecraft_version, "minecraft:menu").index(f"minecraft:{name}")


@pytest.mark.parametrize(("menu", "own"), MENU_SLOTS.items(), ids=list(MENU_SLOTS))
def test_a_menu_lays_out_its_own_slots_then_the_players(menu: str, own: int) -> None:
    tracker = followed(
        open_screen(CHEST, menu_id(menu)),
        set_slot(CHEST, own, slot(STONE, 1)),
        set_slot(CHEST, own + 35, slot(SWORD, 1)),
    )
    view = tracker.view()
    assert len(view.slots) == own + 36
    assert (view.player[9], view.player[8]) == (stack("stone", 1), stack("diamond_sword", 1))


def test_a_crafters_result_comes_after_the_players_slots() -> None:
    # CrafterMenu.addSlots: the 3x3, the 27 and the hotbar, then its result (slot 45).
    tracker = followed(
        open_screen(CHEST, menu_id("crafter_3x3")),
        content(CHEST, [None] * 9 + [slot(STONE, 1)] + [None] * 35 + [slot(SWORD, 1)]),
    )
    view = tracker.view()
    assert (len(view.slots), view.player[9], view.slots[45]) == (
        46,
        stack("stone", 1),
        stack("diamond_sword", 1),
    )
    assert view.player[8] is None


def test_a_lectern_holds_its_book_and_none_of_the_players_slots() -> None:
    # LecternMenu adds one slot and no player inventory: a set slot past it changes nothing.
    tracker = followed(
        open_screen(CHEST, menu_id("lectern")),
        content(CHEST, [slot(SWORD, 1)]),
        set_slot(CHEST, 1, slot(STONE, 1)),
    )
    view = tracker.view()
    assert (view.slots, view.player[9]) == ((stack("diamond_sword", 1),), None)


def mount_screen(window_id: int, columns: int, entity_id: int) -> Received:
    fields = {"window_id": window_id, "inventory_columns": columns, "entity_id": entity_id}
    return ("minecraft:mount_screen_open", fields)


def mount(entity_id: int, kind: str) -> Mapping[int, Entity]:
    return {
        entity_id: Entity(id=entity_id, uuid=uuid.UUID(int=entity_id), type=kind, x=0, y=0, z=0)
    }


@pytest.mark.parametrize(
    ("kind", "columns", "own"),
    [
        ("minecraft:horse", 0, 2),
        ("minecraft:donkey", 5, 17),
        ("minecraft:camel_husk", 0, 2),
        ("minecraft:zombie_nautilus", 3, 2),
    ],
)
def test_a_mount_screen_opens_the_mounts_window(kind: str, columns: int, own: int) -> None:
    # handleMountScreenOpen: a HorseInventoryMenu (saddle, body, then 3 rows of the columns)
    # for an AbstractHorse, a NautilusInventoryMenu (saddle, body) for an AbstractNautilus.
    tracker = InventoryTracker()
    tracker.follow(*mount_screen(CHEST, columns, 7), entities=mount(7, kind))
    tracker.follow(*set_slot(CHEST, own, slot(STONE, 1)))
    view = tracker.view()
    assert (view.window_id, view.menu, len(view.slots)) == (CHEST, kind, own + 36)
    assert view.player[9] == stack("stone", 1)


@pytest.mark.parametrize(
    "entities", [{}, mount(7, "minecraft:pig")], ids=["unknown", "not-a-mount"]
)
def test_a_mount_screen_for_no_mount_opens_nothing(entities: Mapping[int, Entity]) -> None:
    tracker = InventoryTracker()
    tracker.follow(*mount_screen(CHEST, 0, 7), entities=entities)
    assert tracker.view().window_id == 0


def test_a_close_with_no_container_open_keeps_the_inventory_menu() -> None:
    tracker = followed(player_slot(0, slot(STONE, 1)), CLOSE)
    assert tracker.view().slots[36] == stack("stone", 1)


def test_clear_empties_every_slot_and_closes_the_container() -> None:
    tracker = followed(player_slot(0, slot(STONE, 1)), open_screen(CHEST, GENERIC_9X3))
    tracker.clear()
    assert tracker.view() == InventoryTracker().view()


@pytest.mark.parametrize(
    ("whole", "left"),
    [(False, stack("stone", 63)), (True, None)],
    ids=["one", "whole-stack"],
)
def test_remove_from_selected_takes_one_or_the_whole_stack(whole: bool, left: Stack | None) -> None:  # noqa: FBT001
    tracker = followed(player_slot(3, slot(STONE, 64)))
    tracker.remove_from_selected(3, whole=whole)
    assert tracker.view().player[3] == left


def test_a_stacks_item_outside_the_registry_is_named_by_its_number() -> None:
    view = followed(player_slot(0, slot(99_999, 1))).view()
    assert view.player[0] == Stack(item="#99999", count=1)


def test_a_stacks_changed_components_are_kept_as_decoded() -> None:
    patch = {"added": [{"type": "minecraft:damage", "value": 3}], "removed": []}
    view = followed(player_slot(0, {**slot(SWORD, 1), "components": patch})).view()
    assert view.player[0] == Stack(item="minecraft:diamond_sword", count=1, components=patch)


# The Bot


def inventory_after(
    packets: list[Received],
    script: Callable[[Bot], Awaitable[None]] | None = None,
) -> tuple[Inventory, list[tuple[str, Mapping[str, object] | None]]]:
    """A joined Bot's inventory once `packets` came after its first tick and `script` ran.

    Also returns what the Bot sent after that tick, but statistics requests.
    """
    found: list[Inventory] = []
    seen: list[Packet] = []

    async def use(bot: Bot) -> None:
        await bot.join()
        await bot.tick()
        await bot.sync()
        if script is not None:
            await script(bot)
            await bot.sync()
        found.append(bot.inventory)

    transcript = Transcript(group_id="test/inventory", server="fake")
    with_bot(CODEC, transcript, entity_server(seen, packets), use)
    ends = [
        index for index, packet in enumerate(seen) if packet.name == "minecraft:client_tick_end"
    ]
    after = seen[ends[0] + 1 :]
    sent = [
        (packet.name, packet.fields)
        for packet in after
        if packet.name != "minecraft:client_command"
    ]
    return found[0], sent


def test_a_bot_keeps_its_inventory_as_the_server_sets_it() -> None:
    view, _ = inventory_after([open_screen(CHEST, GENERIC_9X3), set_slot(CHEST, 0, slot(STONE, 2))])
    assert (view.window_id, view.slots[0]) == (CHEST, stack("stone", 2))


@pytest.mark.parametrize(
    "fresh",
    [("minecraft:login", LOGIN), ("minecraft:respawn", {**RESPAWN, "data_kept": 0})],
    ids=["login", "respawn"],
)
def test_a_new_player_holds_nothing(fresh: Received) -> None:
    # A play login or any respawn makes a new LocalPlayer, with a new Inventory and menu.
    view, _ = inventory_after(
        [player_slot(0, slot(STONE, 1)), open_screen(CHEST, GENERIC_9X3), fresh]
    )
    assert view == InventoryTracker().view()


def test_close_container_sends_the_open_windows_id_alone_and_closes_it() -> None:
    # LocalPlayer.closeContainer: container_close with the menu's id, outside any tick.
    async def script(bot: Bot) -> None:
        await bot.close_container()

    view, sent = inventory_after([open_screen(CHEST, GENERIC_9X3)], script)
    assert sent == [("minecraft:container_close", {"window_id": CHEST})]
    assert view.window_id == 0


def test_close_container_with_none_open_closes_the_inventory_screen_as_window_0() -> None:
    async def script(bot: Bot) -> None:
        await bot.close_container()

    _, sent = inventory_after([], script)
    assert sent == [("minecraft:container_close", {"window_id": 0})]


def test_a_screen_the_server_opens_while_the_close_is_sent_stays_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # LocalPlayer.closeContainer closes the menu at once: an open_screen read during the send
    # (the reader runs while it drains) opens the menu the Bot holds after.
    async def script(bot: Bot) -> None:
        send = bot._connection.send  # noqa: SLF001 - the send the reader runs beside

        async def read_meanwhile(name: str, /, **fields: object) -> None:
            await send(name, **fields)
            if name == "minecraft:container_close":
                bot._replies.inventory.follow(*open_screen(CHEST + 1, GENERIC_9X3))  # noqa: SLF001

        monkeypatch.setattr(bot._connection, "send", read_meanwhile)  # noqa: SLF001
        await bot.close_container()

    view, _ = inventory_after([open_screen(CHEST, GENERIC_9X3)], script)
    assert view.window_id == CHEST + 1


@pytest.mark.parametrize(
    ("whole", "action", "left"),
    [(False, 5, stack("stone", 63)), (True, 4, None)],
    ids=["one", "whole-stack"],
)
def test_drop_takes_from_the_held_stack_and_says_so_in_one_tick(
    whole: bool,  # noqa: FBT001
    action: int,
    left: Stack | None,
) -> None:
    # MultiPlayerGameMode.dropItem: removeFromSelected first, then player_action DROP_ITEM (5),
    # or DROP_ALL_ITEMS (4) with Ctrl, at the origin facing down with sequence 0.
    async def script(bot: Bot) -> None:
        await bot.drop(all=whole)

    view, sent = inventory_after([player_slot(0, slot(STONE, 64))], script)
    fields = {"action": action, "pos": {"x": 0, "y": 0, "z": 0}, "face": 0, "sequence": 0}
    assert sent == [("minecraft:player_action", fields), TICK_END]
    assert view.player[0] == left


def test_drop_with_an_empty_hand_still_sends_the_action() -> None:
    async def script(bot: Bot) -> None:
        await bot.drop()

    _, sent = inventory_after([], script)
    assert [name for name, _ in sent] == ["minecraft:player_action", "minecraft:client_tick_end"]


def test_drop_refuses_while_a_container_is_open() -> None:
    # The client reads the drop key only with no screen open (Minecraft.tick).
    refused: list[str] = []

    async def script(bot: Bot) -> None:
        with pytest.raises(ProtocolError, match="close_container") as raised:
            await bot.drop()
        refused.append(str(raised.value))

    _, sent = inventory_after([open_screen(CHEST, GENERIC_9X3)], script)
    assert refused
    assert sent == []


def test_inventory_is_a_snapshot() -> None:
    view = InventoryTracker().view()
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(view, "window_id", 1)  # noqa: B010


HORSE = 7
"""A horse's entity id."""


def test_a_horses_screen_is_the_window_drop_refuses_and_close_container_closes() -> None:
    # The Bot knows the horse, so the mount screen opens its window, as the client's does.
    async def script(bot: Bot) -> None:
        with pytest.raises(ProtocolError, match="close_container"):
            await bot.drop()
        await bot.close_container()

    types = registry_names(TARGET.minecraft_version, "minecraft:entity_type")
    horse = added(HORSE, types.index("minecraft:horse"), 1.0, -60.0, 1.0)
    view, sent = inventory_after([horse, mount_screen(CHEST, 0, HORSE)], script)
    assert sent == [("minecraft:container_close", {"window_id": CHEST})]
    assert view.window_id == 0


# Clicks: AbstractContainerMenu.doClick and the menus' quickMoveStack (26.3 client, javap).
# Each starts from slots as vanilla's server sends them (a set_content), and checks the
# container_click the client would send: the changed slots in its Int2ObjectOpenHashMap's order.


def item_id(name: str) -> int:
    return registry_names(TARGET.minecraft_version, "minecraft:item").index(f"minecraft:{name}")


def hashed(name: str, count: int) -> dict[str, object]:
    """A `HASHED_SLOT` value with no component changed."""
    return {"item": item_id(name), "count": count, "components": {"added": [], "removed": []}}


def holding(
    stacks: Mapping[int, tuple[str, int]],
    *,
    chest: bool = False,
    menu: str | None = None,
    carried: tuple[str, int] | None = None,
) -> InventoryTracker:
    """A tracker whose open menu holds `stacks` by slot.

    The menu is the inventory menu, or a chest's, or one of type `menu` (window `CHEST`).
    """
    opened = "minecraft:generic_9x3" if chest else menu
    slots: list[dict[str, object] | None] = [None] * max((46, *(index + 1 for index in stacks)))
    for index, (name, count) in stacks.items():
        slots[index] = slot(item_id(name), count)
    cursor_stack = None if carried is None else slot(item_id(carried[0]), carried[1])
    if opened is None:
        return followed(content(0, slots, state_id=5, carried=cursor_stack))
    window_type = registry_names(TARGET.minecraft_version, "minecraft:menu").index(opened)
    filled = content(CHEST, slots, state_id=5, carried=cursor_stack)
    return followed(open_screen(CHEST, window_type), filled)


def click_sent(
    slot_number: int,
    changed: Sequence[tuple[int, dict[str, object] | None]],
    carried: dict[str, object] | None,
    *,
    button: int = 0,
    mode: int = 0,
) -> dict[str, object]:
    """The container_click fields in the inventory menu, the changed slots in the client's order.

    The order is `_hash_map_order`'s, which a test below pins to what fastutil gives in Java.
    """
    by_slot = dict(changed)
    return {
        "window_id": 0,
        "state_id": 5,
        "slot": slot_number,
        "button": button,
        "mode": mode,
        "changed_slots": [
            {"slot": index, "item": by_slot[index]} for index in _hash_map_order(sorted(by_slot))
        ],
        "carried_item": carried,
    }


def in_chest(sent: dict[str, object]) -> dict[str, object]:
    """`sent` as clicked in the open chest: its window id."""
    return {**sent, "window_id": CHEST}


def test_a_left_click_takes_the_whole_stack() -> None:
    tracker = holding({36: ("stone", 64)})
    assert tracker.click(36, 0, "pickup") == click_sent(36, [(36, None)], hashed("stone", 64))
    view = tracker.view()
    assert (view.slots[36], view.carried, view.player[0]) == (None, stack("stone", 64), None)


@pytest.mark.parametrize(("count", "taken"), [(64, 32), (5, 3), (1, 1)])
def test_a_right_click_takes_half_rounded_up(count: int, taken: int) -> None:
    tracker = holding({9: ("stone", count)})
    left = None if count == taken else hashed("stone", count - taken)
    sent = click_sent(9, [(9, left)], hashed("stone", taken), button=1)
    assert tracker.click(9, 1, "pickup") == sent


@pytest.mark.parametrize(("button", "placed"), [(0, 10), (1, 1)], ids=["left", "right"])
def test_a_click_on_an_empty_slot_puts_down_all_or_one(button: int, placed: int) -> None:
    tracker = holding({}, carried=("stone", 10))
    left = None if placed == 10 else hashed("stone", 10 - placed)
    sent = click_sent(20, [(20, hashed("stone", placed))], left, button=button)
    assert tracker.click(20, button, "pickup") == sent


def test_a_click_merges_the_cursor_into_the_same_item_up_to_its_stack_size() -> None:
    tracker = holding({20: ("stone", 60)}, carried=("stone", 10))
    sent = click_sent(20, [(20, hashed("stone", 64))], hashed("stone", 6))
    assert tracker.click(20, 0, "pickup") == sent


def test_a_click_with_another_item_swaps_it_with_the_cursor() -> None:
    tracker = holding({20: ("stone", 60)}, carried=("diamond_sword", 1))
    sent = click_sent(20, [(20, hashed("diamond_sword", 1))], hashed("stone", 60))
    assert tracker.click(20, 0, "pickup") == sent


def test_an_armor_slot_takes_only_its_own_armor() -> None:
    # ArmorSlot.mayPlace: the item's equippable slot must be the slot's (5 is the head).
    tracker = holding({}, carried=("diamond_helmet", 1))
    assert tracker.click(6, 0, "pickup") == click_sent(6, [], hashed("diamond_helmet", 1))
    sent = click_sent(5, [(5, hashed("diamond_helmet", 1))], None)
    assert tracker.click(5, 0, "pickup") == sent
    assert tracker.view().player[39] == stack("diamond_helmet", 1)


def test_an_armor_slot_holds_one_carved_pumpkin_of_a_stack() -> None:
    # ArmorSlot.getMaxStackSize is 1.
    tracker = holding({}, carried=("carved_pumpkin", 5))
    sent = click_sent(5, [(5, hashed("carved_pumpkin", 1))], hashed("carved_pumpkin", 4))
    assert tracker.click(5, 0, "pickup") == sent


@pytest.mark.parametrize(("button", "left"), [(0, None), (1, 9)], ids=["left", "right"])
def test_a_click_outside_drops_the_cursor_or_one_of_it(button: int, left: int | None) -> None:
    tracker = holding({}, carried=("stone", 10))
    carried = None if left is None else hashed("stone", left)
    sent = click_sent(OUTSIDE, [], carried, button=button)
    assert tracker.click(OUTSIDE, button, "pickup") == sent


def test_a_click_on_a_negative_slot_but_outside_changes_nothing() -> None:
    tracker = holding({}, carried=("stone", 10))
    assert tracker.click(-1, 0, "pickup") == click_sent(-1, [], hashed("stone", 10))


def test_a_shift_click_moves_the_hotbar_into_the_chest_from_its_first_slot() -> None:
    # ChestMenu.quickMoveStack: a player slot goes to the container's, merging first.
    tracker = holding({54: ("stone", 64), 1: ("stone", 60)}, chest=True)
    changed = [(0, hashed("stone", 60)), (1, hashed("stone", 64)), (54, None)]
    sent = in_chest(click_sent(54, changed, None, mode=1))
    assert tracker.click(54, 0, "quick_move") == sent


def test_a_shift_click_moves_the_chest_into_the_player_from_the_last_slot() -> None:
    # A container slot goes to the player's slots from the end: the hotbar's last first.
    tracker = holding({0: ("stone", 64)}, chest=True)
    sent = in_chest(click_sent(0, [(0, None), (62, hashed("stone", 64))], None, mode=1))
    assert tracker.click(0, 0, "quick_move") == sent
    assert tracker.view().player[8] == stack("stone", 64)


def test_a_shift_click_that_fits_nowhere_changes_nothing() -> None:
    full = dict.fromkeys(range(27), ("diamond_sword", 1))
    tracker = holding({**full, 54: ("stone", 64)}, chest=True)
    assert tracker.click(54, 0, "quick_move") == in_chest(click_sent(54, [], None, mode=1))


@pytest.mark.parametrize(
    ("start", "item", "end"),
    [
        (9, "diamond_helmet", 5),
        (36, "shield", 45),
        (9, "stone", 36),
        (36, "stone", 9),
        (5, "diamond_helmet", 9),
        (45, "stone", 9),
    ],
    ids=["armor", "off-hand", "to-hotbar", "to-storage", "out-of-armor", "out-of-off-hand"],
)
def test_a_shift_click_in_the_inventory_menu_goes_where_the_client_puts_it(
    start: int, item: str, end: int
) -> None:
    # InventoryMenu.quickMoveStack: armor to its empty armor slot, an off-hand item to the empty
    # off hand, else the 27 to the hotbar and back; the armor and off hand to the 27 first.
    tracker = holding({start: (item, 1)})
    sent = click_sent(start, [(start, None), (end, hashed(item, 1))], None, mode=1)
    assert tracker.click(start, 0, "quick_move") == sent


def test_a_shift_click_merges_into_partial_stacks_before_an_empty_slot() -> None:
    tracker = holding({9: ("stone", 30), 40: ("stone", 50)})
    changed = [(9, None), (40, hashed("stone", 64)), (36, hashed("stone", 16))]
    assert tracker.click(9, 0, "quick_move") == click_sent(9, changed, None, mode=1)


def test_a_number_key_swaps_a_chest_slot_with_that_hotbar_slot() -> None:
    # SWAP, button 3: the chest's slot 0 and Inventory index 3 (the chest menu's slot 57).
    tracker = holding({57: ("diamond_sword", 1)}, chest=True)
    changed = [(0, hashed("diamond_sword", 1)), (57, None)]
    sent = in_chest(click_sent(0, changed, None, button=3, mode=2))
    assert tracker.click(0, 3, "swap") == sent
    assert tracker.view().player[3] is None


def test_the_f_key_swaps_with_the_off_hand() -> None:
    tracker = holding({9: ("stone", 5)})
    sent = click_sent(9, [(9, None), (45, hashed("stone", 5))], None, button=40, mode=2)
    assert tracker.click(9, 40, "swap") == sent


def test_a_swap_with_a_button_that_is_no_key_changes_nothing() -> None:
    # Button 9 would be Inventory index 9, the inventory menu's slot 9: clicked over slot 20.
    tracker = holding({20: ("stone", 5)})
    assert tracker.click(20, 9, "swap") == click_sent(20, [], None, button=9, mode=2)


@pytest.mark.parametrize(("button", "left"), [(0, 63), (1, None)], ids=["one", "stack"])
def test_q_over_a_slot_drops_one_or_the_stack(button: int, left: int | None) -> None:
    tracker = holding({9: ("stone", 64)})
    remaining = None if left is None else hashed("stone", left)
    sent = click_sent(9, [(9, remaining)], None, button=button, mode=4)
    assert tracker.click(9, button, "throw") == sent


def test_q_with_a_stack_on_the_cursor_changes_nothing() -> None:
    tracker = holding({9: ("stone", 64)}, carried=("dirt", 1))
    assert tracker.click(9, 0, "throw") == click_sent(9, [], hashed("dirt", 1), mode=4)


def test_a_double_click_gathers_the_item_full_stacks_last() -> None:
    # PICKUP_ALL: from slot 0 forward, first skipping full stacks; up to the stack size.
    stacks = {10: ("stone", 20), 11: ("stone", 64), 12: ("stone", 30)}
    tracker = holding(stacks, carried=("stone", 10))
    changed = [(10, None), (12, None), (11, hashed("stone", 60))]
    sent = click_sent(20, changed, hashed("stone", 64), mode=6)
    assert tracker.click(20, 0, "pickup_all") == sent


def test_a_drag_spreads_the_cursor_evenly_and_keeps_the_rest() -> None:
    # QUICK_CRAFT: start (button 0), each slot (button 1), end (button 2): 64 over 3 is 21 each.
    tracker = holding({}, carried=("stone", 64))
    carried = hashed("stone", 64)
    assert tracker.click(OUTSIDE, 0, "quick_craft") == click_sent(OUTSIDE, [], carried, mode=5)
    for index in (9, 10, 11):
        sent = click_sent(index, [], carried, button=1, mode=5)
        assert tracker.click(index, 1, "quick_craft") == sent
    changed = [(index, hashed("stone", 21)) for index in (9, 10, 11)]
    sent = click_sent(OUTSIDE, changed, hashed("stone", 1), button=2, mode=5)
    assert tracker.click(OUTSIDE, 2, "quick_craft") == sent


def test_a_right_drag_puts_one_in_each_slot() -> None:
    tracker = holding({10: ("stone", 5)}, carried=("stone", 3))
    for button, index in ((4, OUTSIDE), (5, 9), (5, 10)):
        tracker.click(index, button, "quick_craft")
    changed = [(9, hashed("stone", 1)), (10, hashed("stone", 6))]
    sent = click_sent(OUTSIDE, changed, hashed("stone", 1), button=6, mode=5)
    assert tracker.click(OUTSIDE, 6, "quick_craft") == sent


def test_a_drag_over_one_slot_is_a_click_on_it() -> None:
    tracker = holding({}, carried=("stone", 64))
    for button, index in ((0, OUTSIDE), (1, 9)):
        tracker.click(index, button, "quick_craft")
    sent = click_sent(OUTSIDE, [(9, hashed("stone", 64))], None, button=2, mode=5)
    assert tracker.click(OUTSIDE, 2, "quick_craft") == sent


def test_another_click_during_a_drag_ends_it_and_does_nothing_else() -> None:
    tracker = holding({}, carried=("stone", 64))
    tracker.click(OUTSIDE, 0, "quick_craft")
    tracker.click(9, 1, "quick_craft")
    assert tracker.click(10, 0, "pickup") == click_sent(10, [], hashed("stone", 64))
    sent = click_sent(OUTSIDE, [], hashed("stone", 64), button=2, mode=5)
    assert tracker.click(OUTSIDE, 2, "quick_craft") == sent


def test_a_middle_click_clone_changes_nothing_for_a_survival_player() -> None:
    tracker = holding({9: ("stone", 5)})
    assert tracker.click(9, 2, "clone") == click_sent(9, [], None, button=2, mode=3)


@pytest.mark.parametrize(
    ("stacks", "slot_number", "button", "mode", "match"),
    [
        ({}, 9, 0, "drag", "mode must be one of"),
        ({}, 40_000, 0, "pickup", "Short"),
        ({}, 9, 200, "pickup", "Byte"),
        ({}, 0, 0, "pickup", "crafting result"),
        ({}, OUTSIDE, 0, "swap", "not one of the menu's 46 slots"),
        ({9: ("bundle", 1)}, 9, 0, "pickup", "bundle"),
        ({5: ("diamond_helmet", 1), 36: ("carved_pumpkin", 5)}, 5, 0, "swap", "elsewhere"),
    ],
    ids=["mode", "slot", "button", "result", "swap-outside", "bundle", "swap-back"],
)
def test_a_click_the_bot_cannot_send_or_predict_is_refused_and_changes_nothing(
    stacks: dict[int, tuple[str, int]], slot_number: int, button: int, mode: str, match: str
) -> None:
    # The last: pumpkins over a helmet in the head slot. The head takes one pumpkin and the
    # helmet goes back through Inventory.add, which the Bot does not predict.
    tracker = holding(stacks)
    before = tracker.view()
    with pytest.raises(ValueError, match=match):
        tracker.click(slot_number, button, mode)
    assert tracker.view() == before


def test_a_stack_whose_components_change_cannot_be_hashed_so_the_click_is_refused() -> None:
    patch = {"added": [{"type": "minecraft:damage", "value": 3}], "removed": []}
    tracker = followed(player_slot(9, {**slot(SWORD, 1), "components": patch}))
    before = tracker.view()
    with pytest.raises(ValueError, match="hash"):
        tracker.click(9, 0, "pickup")
    assert tracker.view() == before


def test_a_click_in_a_menu_the_bot_does_not_predict_is_refused() -> None:
    tracker = followed(open_screen(CHEST, FURNACE), content(CHEST, [slot(STONE, 1), None, None]))
    with pytest.raises(ValueError, match="furnace"):
        tracker.click(0, 0, "pickup")


RECORDED_ORDERS = {
    (0, 54): [0, 54],
    (36, 37): [37, 36],
    (5, 36, 45): [36, 5, 45],
    (1, 2, 3, 4, 9, 10, 11, 12, 13): [2, 4, 12, 13, 9, 11, 10, 1, 3],
    tuple(range(30)): [
        *(0, 29, 25, 4, 12, 13, 8, 9, 28, 24, 26, 18, 16, 17, 19),
        *(23, 20, 22, 21, 2, 27, 6, 15, 14, 11, 10, 1, 3, 7, 5),
    ],
    tuple(range(9, 45)): [
        *(33, 29, 25, 37, 12, 13, 9, 30, 28, 24, 18, 26, 16, 17, 19, 23, 20, 22),
        *(21, 35, 39, 27, 15, 14, 10, 11, 31, 32, 34, 38, 36, 44, 42, 41, 40, 43),
    ],
    tuple(range(1, 25)): [
        *(2, 6, 4, 15, 14, 12, 13, 8, 9, 11, 10, 1),
        *(3, 24, 7, 23, 5, 16, 17, 19, 18, 22, 21, 20),
    ],
    (1, 3, 6, 7, 10, 15, 16, 22, 23, 24, 29, 30, 33, 34, 39, 41, 44, 47, 49, 50, 53, 54, 58, 60): [
        *(33, 58, 29, 39, 50, 6, 49, 47, 15, 54, 53, 34),
        *(10, 30, 1, 3, 24, 7, 16, 44, 23, 41, 22, 60),
    ],
}
"""What `Int2ObjectOpenHashMap()` (fastutil 8.5.18, the 26.3 jar's) iterates in Java, given the
keys in ascending order. The 30 and 36 keys are past a rehash; the two sets of 24 are the most
the first table holds (it grows on the 25th insert: `size++ >= maxFill`, 24)."""


@pytest.mark.parametrize(
    ("keys", "order"),
    RECORDED_ORDERS.items(),
    ids=[f"{len(keys)}-keys-from-{keys[0]}-to-{keys[-1]}" for keys in RECORDED_ORDERS],
)
def test_the_changed_slots_come_in_the_clients_hash_map_order(
    keys: tuple[int, ...], order: list[int]
) -> None:
    assert _hash_map_order(list(keys)) == order


def test_a_bot_click_sends_its_prediction_alone() -> None:
    # A click is a mouse callback between ticks: no client_tick_end follows it.
    async def script(bot: Bot) -> None:
        await bot.click(36)

    view, sent = inventory_after([player_slot(0, slot(STONE, 64))], script)
    fields = {
        "window_id": 0,
        "state_id": 0,
        "slot": 36,
        "button": 0,
        "mode": 0,
        "changed_slots": [{"slot": 36, "item": None}],
        "carried_item": hashed("stone", 64),
    }
    assert sent == [("minecraft:container_click", fields)]
    assert view.carried == stack("stone", 64)


def test_the_changed_slots_of_25_keys_come_from_the_grown_table() -> None:
    # The 25th key grows the table from 32 to 64 (fastutil: size++ >= maxFill, 24), recorded.
    keys = [1, 2, 5, 7, 8, 9, 14, 15, 17, 18, 25, 28, 29, 31, 32, 37, 39, 42, 49, 52, 53, 54, 55]
    keys += [58, 59]
    order = [29, 25, 58, 37, 49, 54, 8, 9, 53, 28, 59, 17, 18, 2, 39, 15, 14, 55, 31, 52, 32]
    order += [1, 7, 5, 42]
    assert _hash_map_order(keys) == order


def test_a_shulker_boxs_slots_refuse_a_shulker_box() -> None:
    # ShulkerBoxSlot.mayPlace: Item.canFitInsideContainerItems, false for a ShulkerBoxBlock item.
    slots: list[dict[str, object] | None] = [None] * 63
    slots[54] = slot(item_id("red_shulker_box"), 1)
    shulker_box = 20
    tracker = followed(open_screen(CHEST, shulker_box), content(CHEST, slots, state_id=5))
    assert tracker.click(54, 0, "quick_move") == in_chest(click_sent(54, [], None, mode=1))


def test_a_drag_leaves_out_a_slot_once_each_dragged_slot_would_get_less_than_one() -> None:
    # A slot joins the drag only while the cursor holds more items than the drag has slots.
    tracker = holding({}, carried=("stone", 2))
    for button, index in ((0, OUTSIDE), (1, 9), (1, 10), (1, 11)):
        tracker.click(index, button, "quick_craft")
    changed = [(9, hashed("stone", 1)), (10, hashed("stone", 1))]
    sent = click_sent(OUTSIDE, changed, None, button=2, mode=5)
    assert tracker.click(OUTSIDE, 2, "quick_craft") == sent


def test_a_swap_into_an_armor_slot_takes_one_of_a_stack() -> None:
    tracker = holding({36: ("carved_pumpkin", 5)})
    changed = [(5, hashed("carved_pumpkin", 1)), (36, hashed("carved_pumpkin", 4))]
    assert tracker.click(5, 0, "swap") == click_sent(5, changed, None, mode=2)


def test_a_refused_drag_end_keeps_the_drag_for_the_next_click() -> None:
    # A drag over one slot ends as a click on it, which the Bot refuses with a bundle; the drag
    # it had is kept, so ending it again is refused again.
    tracker = holding({}, carried=("bundle", 1))
    for button, index in ((0, OUTSIDE), (1, 9)):
        tracker.click(index, button, "quick_craft")
    for _ in range(2):
        with pytest.raises(ValueError, match="bundle"):
            tracker.click(OUTSIDE, 2, "quick_craft")


def test_a_slot_that_refuses_its_own_stack_gives_it_only_whole() -> None:
    # Slot.tryRemove: a slot that may not take back what it holds (allowModification false;
    # stone in the head slot, as a server may put it) gives nothing short of the whole stack.
    tracker = holding({5: ("stone", 10)}, carried=("stone", 60))
    assert tracker.click(5, 0, "pickup") == click_sent(5, [], hashed("stone", 60))


def test_a_cursor_whose_components_differ_from_the_slots_swaps_rather_than_merges() -> None:
    # isSameItemSameComponents: the patched stack would go into the slot, which the Bot cannot
    # hash, so the click is refused; merged, nothing would need hashing.
    patch = {"added": [{"type": "minecraft:custom_name", "value": "x"}], "removed": []}
    filled = content(0, [None] * 46, carried={**slot(STONE, 10), "components": patch})
    tracker = followed(filled, set_slot(0, 20, slot(STONE, 10)))
    with pytest.raises(ValueError, match="hash"):
        tracker.click(20, 0, "pickup")


def test_a_shift_click_repeats_while_the_slot_keeps_the_item() -> None:
    # quickMoveStack moves one carved pumpkin into the empty head (ArmorSlot holds one), and
    # doClick repeats it while the slot still holds the item: the rest goes to the hotbar.
    tracker = holding({9: ("carved_pumpkin", 64)})
    changed = [(5, hashed("carved_pumpkin", 1)), (9, None), (36, hashed("carved_pumpkin", 63))]
    assert tracker.click(9, 0, "quick_move") == click_sent(9, changed, None, mode=1)


@pytest.mark.parametrize(
    ("item", "taken"), [("diamond_helmet", 5), ("shield", 45)], ids=["head", "off-hand"]
)
def test_a_shift_click_passes_over_a_full_armor_slot_or_off_hand(item: str, taken: int) -> None:
    # InventoryMenu.quickMoveStack goes to the armor slot or off hand only while it is empty.
    tracker = holding({taken: (item, 1), 9: (item, 1)})
    changed = [(9, None), (36, hashed(item, 1))]
    assert tracker.click(9, 0, "quick_move") == click_sent(9, changed, None, mode=1)


def drag(tracker: InventoryTracker, kind: int, slots: Sequence[int]) -> dict[str, object]:
    """Drag over `slots`: start, each slot, end; buttons carry the drag's `kind` in bits 2-3.

    Returns the container_click of the end.
    """
    tracker.click(OUTSIDE, kind << 2, "quick_craft")
    for index in slots:
        tracker.click(index, kind << 2 | 1, "quick_craft")
    return tracker.click(OUTSIDE, kind << 2 | 2, "quick_craft")


def test_a_right_drag_puts_one_in_each_slot_however_many_the_cursor_holds() -> None:
    tracker = holding({}, carried=("stone", 10))
    changed = [(9, hashed("stone", 1)), (10, hashed("stone", 1))]
    sent = click_sent(OUTSIDE, changed, hashed("stone", 8), button=6, mode=5)
    assert drag(tracker, 1, [9, 10]) == sent


def test_a_right_drag_over_one_slot_is_a_right_click_on_it() -> None:
    tracker = holding({}, carried=("stone", 64))
    sent = click_sent(OUTSIDE, [(9, hashed("stone", 1))], hashed("stone", 63), button=6, mode=5)
    assert drag(tracker, 1, [9]) == sent


def test_a_middle_drag_changes_nothing_for_a_survival_player() -> None:
    # Type 2 puts a full stack in each slot, which needs infinite materials: doClick resets it.
    tracker = holding({}, carried=("stone", 64))
    sent = click_sent(OUTSIDE, [], hashed("stone", 64), button=10, mode=5)
    assert drag(tracker, 2, [9, 10]) == sent


def test_a_drag_leaves_out_a_slot_that_refuses_the_item() -> None:
    # Stone over the head and slot 9: the head refuses it, so the drag is one slot, a click.
    tracker = holding({}, carried=("stone", 64))
    sent = click_sent(OUTSIDE, [(9, hashed("stone", 64))], None, button=2, mode=5)
    assert drag(tracker, 0, [5, 9]) == sent


def test_a_drag_puts_no_more_in_a_slot_than_it_holds() -> None:
    # 10 carved pumpkins over the head and slot 9: 5 each, but the head holds one.
    tracker = holding({}, carried=("carved_pumpkin", 10))
    changed = [(5, hashed("carved_pumpkin", 1)), (9, hashed("carved_pumpkin", 5))]
    sent = click_sent(OUTSIDE, changed, hashed("carved_pumpkin", 4), button=2, mode=5)
    assert drag(tracker, 0, [5, 9]) == sent


def test_a_cursor_too_big_for_the_slot_does_not_swap_with_it() -> None:
    # 5 carved pumpkins onto a helmet in the head: the head takes pumpkins, but only one.
    tracker = holding({5: ("diamond_helmet", 1)}, carried=("carved_pumpkin", 5))
    assert tracker.click(5, 0, "pickup") == click_sent(5, [], hashed("carved_pumpkin", 5))


@pytest.mark.parametrize(
    "stacks",
    [{36: ("stone", 1)}, {36: ("stone", 1), 5: ("diamond_helmet", 1)}],
    ids=["empty", "held"],
)
def test_a_number_key_puts_nothing_in_a_slot_that_refuses_the_item(
    stacks: dict[int, tuple[str, int]],
) -> None:
    tracker = holding(stacks)
    assert tracker.click(5, 0, "swap") == click_sent(5, [], None, mode=2)


def test_a_pickup_with_a_button_past_right_changes_nothing() -> None:
    tracker = holding({9: ("stone", 64)})
    assert tracker.click(9, 2, "pickup") == click_sent(9, [], None, button=2)


def test_a_right_double_click_gathers_from_the_last_slot() -> None:
    # Button 1 goes from the menu's last slot back; the cursor fills before slot 10 empties.
    tracker = holding({10: ("stone", 30), 12: ("stone", 40)}, carried=("stone", 10))
    changed = [(10, hashed("stone", 16)), (12, None)]
    sent = click_sent(20, changed, hashed("stone", 64), button=1, mode=6)
    assert tracker.click(20, 1, "pickup_all") == sent


def test_a_double_click_never_takes_from_the_crafting_result() -> None:
    # InventoryMenu.canTakeItemForPickAll is false for the result slot.
    tracker = holding({0: ("stone", 5)}, carried=("stone", 10))
    assert tracker.click(20, 0, "pickup_all") == click_sent(20, [], hashed("stone", 10), mode=6)


def test_a_double_click_on_a_slot_that_holds_a_stack_changes_nothing() -> None:
    tracker = holding({10: ("stone", 5), 20: ("stone", 5)}, carried=("stone", 10))
    assert tracker.click(20, 0, "pickup_all") == click_sent(20, [], hashed("stone", 10), mode=6)


def test_a_shulker_box_menus_player_slots_take_a_shulker_box() -> None:
    # ShulkerBoxSlot is only the box's own 27; the player's slots take anything.
    tracker = holding({}, menu="minecraft:shulker_box", carried=("red_shulker_box", 1))
    sent = in_chest(click_sent(27, [(27, hashed("red_shulker_box", 1))], None))
    assert tracker.click(27, 0, "pickup") == sent


@pytest.mark.parametrize(
    ("menu", "size"),
    [
        ("generic_9x1", 9),
        ("generic_9x2", 18),
        ("generic_9x3", 27),
        ("generic_9x4", 36),
        ("generic_9x5", 45),
        ("generic_9x6", 54),
        ("generic_3x3", 9),
        ("hopper", 5),
        ("shulker_box", 27),
    ],
)
def test_a_menu_lays_out_its_containers_slots_then_the_players(menu: str, size: int) -> None:
    # ChestMenu, DispenserMenu, HopperMenu, ShulkerBoxMenu: the container, the 27, the hotbar.
    tracker = holding({size: ("stone", 1)}, menu=f"minecraft:{menu}")
    view = tracker.view()
    assert (len(view.slots), view.player[9]) == (size + 36, stack("stone", 1))


@pytest.mark.parametrize("index", [41, 42], ids=["body", "saddle"])
def test_the_body_and_saddle_are_player_inventory_indexes(index: int) -> None:
    tracker = followed(player_slot(index, slot(STONE, 1)))
    assert tracker.view().player[index] == stack("stone", 1)


def test_q_with_a_button_past_ctrl_drops_the_whole_stack() -> None:
    # doClick takes the slot's count for any button but 0, and repeats only for button 1.
    tracker = holding({9: ("stone", 64)})
    assert tracker.click(9, 2, "throw") == click_sent(9, [(9, None)], None, button=2, mode=4)


# ArmorSlot.mayPickup: a survival player may not take from an armor slot a stack enchanted with
# an enchantment that prevents armor change (curse of binding, in the vanilla data pack).

ENCHANTMENTS = ("minecraft:protection", "minecraft:binding_curse")
"""The server's `minecraft:enchantment` registry, in the order its `registry_data` sent it."""


def enchanted(enchantment: int) -> dict[str, object]:
    """A diamond helmet enchanted with `ENCHANTMENTS[enchantment]`, as the codec decodes it."""
    value = [{"enchantment": enchantment, "level": 1}]
    patch = {"added": [{"type": "minecraft:enchantments", "value": value}], "removed": []}
    return {**slot(item_id("diamond_helmet"), 1), "components": patch}


def wearing(
    enchantment: int,
    stacks: Mapping[int, tuple[str, int]] | None = None,
    carried: tuple[str, int] | None = None,
    enchantments: tuple[str, ...] | None = ENCHANTMENTS,
) -> InventoryTracker:
    """The inventory menu with an enchanted helmet in the head slot (5) and `stacks`."""
    tracker = holding(stacks or {}, carried=carried)
    tracker.enchantments = enchantments
    tracker.follow(*set_slot(0, 5, enchanted(enchantment), state_id=5))
    return tracker


@pytest.mark.parametrize(
    ("button", "mode"),
    [(0, "pickup"), (1, "pickup"), (0, "quick_move"), (0, "swap"), (0, "throw"), (1, "throw")],
)
def test_a_cursed_armor_slot_gives_up_nothing(button: int, mode: str) -> None:
    tracker = wearing(1)
    before = tracker.view()
    sent = click_sent(5, [], None, button=button, mode=CLICK_MODES[mode])
    assert tracker.click(5, button, mode) == sent
    assert tracker.view() == before


def test_a_cursed_armor_slot_takes_nothing_from_the_cursor() -> None:
    # The whole held-slot branch of PICKUP needs mayPickup, the merge and the swap with it.
    tracker = wearing(1, carried=("stone", 10))
    assert tracker.click(5, 0, "pickup") == click_sent(5, [], hashed("stone", 10))


def test_a_double_click_on_a_cursed_armor_slot_gathers_as_on_an_empty_one() -> None:
    # PICKUP_ALL gathers when the clicked slot is empty or the player may not take from it.
    tracker = wearing(1, {9: ("stone", 20)}, carried=("stone", 10))
    sent = click_sent(5, [(9, None)], hashed("stone", 30), mode=6)
    assert tracker.click(5, 0, "pickup_all") == sent


def test_an_armor_slot_with_another_enchantment_gives_its_stack_up() -> None:
    tracker = wearing(0)
    assert tracker.click(5, 0, "throw") == click_sent(5, [(5, None)], None, mode=4)


def test_an_enchanted_armor_slot_is_refused_while_the_enchantments_are_unknown() -> None:
    tracker = wearing(0, enchantments=None)
    before = tracker.view()
    with pytest.raises(ValueError, match="enchantment"):
        tracker.click(5, 0, "throw")
    assert tracker.view() == before


def registry(*names: str) -> "Packet":
    entries = [{"entry_id": name, "data": None} for name in names]
    return arrived(
        State.CONFIGURATION,
        "minecraft:registry_data",
        registry_id="minecraft:enchantment",
        entries=entries,
    )


def test_the_enchantments_come_from_each_configurations_registry_data() -> None:
    # RegistryDataCollector appends each registry_data's entries, and a new configuration
    # starts a new collector: the ids are the order sent.
    replies = Replies()
    finish = arrived(State.CONFIGURATION, "minecraft:finish_configuration")
    answers(replies, registry("minecraft:protection"), registry("minecraft:binding_curse"), finish)
    assert replies.inventory.enchantments == ENCHANTMENTS
    answers(replies, registry("minecraft:binding_curse"), finish)
    assert replies.inventory.enchantments == ("minecraft:binding_curse",)


def test_a_slot_that_refuses_its_own_stack_gives_it_whole_onto_a_cursor_with_just_the_room() -> (
    None
):
    # Slot.tryRemove: without allowModification, a take short of the whole stack gives nothing,
    # but 10 stone onto a cursor of 54 is the whole stack.
    tracker = holding({5: ("stone", 10)}, carried=("stone", 54))
    assert tracker.click(5, 0, "pickup") == click_sent(5, [(5, None)], hashed("stone", 64))


def test_a_double_click_with_a_button_past_right_also_gathers_from_the_last_slot() -> None:
    # PICKUP_ALL goes forward only for button 0.
    tracker = holding({10: ("stone", 30), 12: ("stone", 40)}, carried=("stone", 10))
    changed = [(10, hashed("stone", 16)), (12, None)]
    sent = click_sent(20, changed, hashed("stone", 64), button=2, mode=6)
    assert tracker.click(20, 2, "pickup_all") == sent


def test_a_cursed_stack_outside_the_armor_slots_is_taken_as_any_other() -> None:
    # Only ArmorSlot refuses: a cursed helmet in slot 9 is dropped (Q) as any stack is.
    tracker = holding({})
    tracker.enchantments = ENCHANTMENTS
    tracker.follow(*set_slot(0, 9, enchanted(1), state_id=5))
    assert tracker.click(9, 0, "throw") == click_sent(9, [(9, None)], None, mode=4)


def test_a_cursed_armor_slot_swaps_with_neither_the_cursor_nor_a_hotbar_key() -> None:
    # A plain helmet would fit the head slot, so without mayPickup each would swap.
    tracker = wearing(1, {36: ("diamond_helmet", 1)}, carried=("diamond_helmet", 1))
    assert tracker.click(5, 0, "pickup") == click_sent(5, [], hashed("diamond_helmet", 1))
    sent = click_sent(5, [], hashed("diamond_helmet", 1), mode=2)
    assert tracker.click(5, 0, "swap") == sent
