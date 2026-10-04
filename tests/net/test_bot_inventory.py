"""The Bot's inventory: what the server says is in each slot, kept as the 26.3 client keeps it.

`ClientPacketListener` (26.3 client, javap): `container_set_content` and `container_set_slot`
for window 0 go to the player's inventory menu, even with a container open, and for the open
container's id to its menu; any other id changes nothing. `set_cursor_item` sets the open
menu's carried stack, `set_player_inventory` an inventory index. A menu's player slots are the
player's `Inventory`, so a change through one shows in every menu.
"""

import dataclasses
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING

import pytest

from mscts.bot import Bot
from mscts.inventory import Inventory, InventoryTracker, Stack
from mscts.net import ProtocolError
from mscts.transcript import Transcript
from tests.net.fakes import with_bot
from tests.net.test_bot_entities import entity_server
from tests.net.test_bot_move import CODEC, LOGIN, RESPAWN, TICK_END

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


def test_a_menu_the_bot_does_not_lay_out_holds_its_contents_as_sent() -> None:
    # A furnace's slots are its contents, in order, with no link to the player's inventory.
    tracker = followed(open_screen(CHEST, FURNACE), content(CHEST, [slot(STONE, 1), None]))
    tracker.follow(*set_slot(CHEST, 1, slot(SWORD, 1)))
    view = tracker.view()
    assert (view.menu, view.slots) == (
        "minecraft:furnace",
        (stack("stone", 1), stack("diamond_sword", 1)),
    )


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
