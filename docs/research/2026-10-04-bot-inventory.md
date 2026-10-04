# How a client keeps its inventory and the open container — 2026-10-04

Evidence behind #28's `Bot.inventory`, `close_container` and `drop`. Facts
are **verified** with `scripts/research/javap.py` on the 26.3 client jar
unless a line says otherwise. The packet layouts are the schemas in
`codec/schemas/play/inventory.py`, which the wiki's revision 3810839 agrees
with.

## Menus

- The player always has its inventory menu (`Player.inventoryMenu`, window
  id 0). `Player.containerMenu` is the open one: the inventory menu, or the
  menu of the last `open_screen`. A new `LocalPlayer`, which every play
  `login` and every `respawn` makes, starts with an empty `Inventory` and
  its own inventory menu open.
- A menu's slots point into containers. Its player slots point into the
  player's `Inventory`, so a stack set through one menu shows in all of them.
- `InventoryMenu`: slot 0 the crafting result, 1 to 4 the 2x2 grid, 5 to 8
  the armor from the head down (`Inventory` 39, 38, 37, 36), 9 to 35
  `Inventory` 9 to 35, 36 to 44 the hotbar (`Inventory` 0 to 8), 45 the off
  hand (`Inventory` 40).
- `ChestMenu` (`generic_9x1` to `generic_9x6`), `DispenserMenu`
  (`generic_3x3`), `HopperMenu` (`hopper`) and `ShulkerBoxMenu`
  (`shulker_box`): the container's slots (9 per row, 9, 5 and 27), then
  `Inventory` 9 to 35, then the hotbar, 0 to 8.
- `Inventory` has 43 indexes: the hotbar 0 to 8, the rest 9 to 35, then
  feet, legs, chest and head (36 to 39), the off hand (40), the body (41)
  and the saddle (42) (`Inventory.EQUIPMENT_SLOT_MAPPING`).

## What each packet does (`ClientPacketListener`)

- **`container_set_slot`**: window 0 goes to the inventory menu, even with a
  container open; the open menu's id goes to that menu; any other id is
  ignored. `setItem` sets the slot, then the menu's state id. A slot the
  menu does not have throws (the Bot ignores it).
- **`container_set_content`**: the same choice of menu, then
  `initializeContents`: each slot sent, then the carried stack, then the
  state id.
- **`set_cursor_item`**: the open menu's carried stack.
- **`set_player_inventory`**: `Inventory.setItem` at that index. An index
  past 42 changes nothing; a negative one throws (the Bot ignores it).
- **`open_screen`**: `MenuScreens.create` makes the menu for the type with
  the window id, and it becomes the open one, its carried stack empty.
- **`container_close`** (clientbound): `clientSideCloseContainer`: the
  inventory menu is open again. Nothing is sent.

## What the client sends

- **Closing a screen** (`LocalPlayer.closeContainer`): `container_close`
  with the open menu's window id, then the client-side close. The player's
  own inventory screen sends window 0. It is sent when the screen closes,
  not in a tick.
- **Drop** (the Q key; `Minecraft.handleKeybinds`, not for a spectator):
  `MultiPlayerGameMode.dropItem` takes one item, or the stack with Ctrl,
  from the held slot (`Inventory.removeFromSelected`), then
  `ensureHasSentCarriedItem`, then `player_action` DROP_ITEM (5) or
  DROP_ALL_ITEMS (4) at 0 0 0, face down, sequence 0. It sends that with an
  empty hand too. The swing that follows sends nothing.
- `Minecraft.tick` calls `handleKeybinds` only when no screen is open, so
  the client never drops this way with a container open.
