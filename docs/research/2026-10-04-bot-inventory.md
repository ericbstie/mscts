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
- Every other `open_screen` menu also ends with `Inventory` 9 to 35 and the
  hotbar (`addStandardInventorySlots`), after its own slots: 3 for the
  furnace, blast furnace, smoker, anvil, grindstone, cartography table and
  merchant; 10 for the crafting table (result, then the 3x3); 5 for the
  brewing stand; 4 for the loom and the smithing table; 2 for the
  enchanting table and the stonecutter; 1 for the beacon. The anvil's and
  the smithing table's come through `ItemCombinerMenu` (2 and 3 inputs,
  then the result). The crafter puts its 3x3 first and its result last,
  after the player's slots (`CrafterMenu.addSlots`). The lectern has one
  slot, the book, and none of the player's.
- A mount's inventory (`mount_screen_open`): `handleMountScreenOpen` looks
  the entity up in the client's level. For an `AbstractHorse` (horse,
  donkey, mule, llama, trader llama, skeleton and zombie horse, camel,
  camel husk) it opens a `HorseInventoryMenu`: the saddle, the body, then 3
  rows of the packet's columns, then the player's slots. For an
  `AbstractNautilus` (nautilus, zombie nautilus) a `NautilusInventoryMenu`:
  the saddle and the body, then the player's slots. For any other entity, or
  none, nothing opens.
- **The server sends the player's inventory changes through the open
  window only.** `ServerPlayer.tick` broadcasts only `containerMenu`'s
  changes, so with a furnace open a `/give` arrives as a
  `container_set_slot` for the furnace's window at its player slot (30 for
  the hotbar's first). On the close, `doCloseContainer` copies the menu's
  remote slots to the inventory menu (`transferState`), so the server never
  resends them for window 0. Verified live by review B (`/give` with a
  furnace open), and pinned by `test_bot_inventory_reference.py`.
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
- **`mount_screen_open`**: the mount's menu, as above, becomes the open one.
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

## Clicks

- **What is sent** (`MultiPlayerGameMode.handleContainerInput`): a click
  for another window than the open one is dropped with a warning. Otherwise
  the client copies every slot's stack, runs `AbstractContainerMenu.clicked`,
  and puts each slot whose stack no longer `ItemStack.matches` its copy into
  a new `Int2ObjectOpenHashMap()`, in slot order. It sends
  `container_click` with the window id, the menu's state id (which a click
  never changes), the slot (`Shorts.checkedCast`), the button
  (`SignedBytes.checkedCast`), the mode, that map and the cursor's stack,
  each stack as a `HashedStack`. A click is a mouse or key callback, sent at
  once, outside the tick.
- **Map order.** The changed slots go on the wire in the map's iteration
  order. fastutil 8.5.18 (the jar's) starts the table at 32 entries
  (16 expected, load factor 0.75) and doubles it when a put finds 24 or
  more entries already in. A key goes at `HashCommon.mix(key) & mask`, where
  `mix` is the key times `0x9E3779B9`, xor that shifted right by 16, then
  the next free position after it. Iteration gives key 0 first (it is kept
  apart), then the table from its last position down. Recorded in Java for
  seven key sets, among them three past the growth
  (`tests/net/test_bot_inventory.py`).
- **`HashedStack`**: an empty stack is `false`. Otherwise the item, the
  count, and the component patch hashed with the connection's hash
  generator (`decoratedHashOpsGenenerator`). A stack whose patch is empty
  sends empty lists. The Bot cannot hash any other patch.
- **`doClick`**, mode by mode:
  - QUICK_CRAFT (a drag) is a state machine on the button: header
    `button & 3` (start 0, add 1, end 2) and type `button >> 2 & 3`. Type 0
    spreads the cursor evenly (`floor(count / slots)`), 1 puts one in each
    slot, and 2 (a full stack each) needs infinite materials. A slot joins
    the drag only while the cursor holds more items than the drag has slots.
    A drag over one slot ends as a PICKUP on it with the type as the button.
    Any other click during a drag ends the drag and does nothing else.
  - PICKUP and QUICK_MOVE take button 0 or 1. Slot -999 drops the cursor
    (all, or one), and another negative slot does nothing.
  - QUICK_MOVE calls the menu's `quickMoveStack` until it moves nothing or
    the slot holds another item.
  - PICKUP with an empty cursor takes the stack, or half rounded up. With a
    stack on the cursor it puts down all of it, or one. On a slot holding
    the same stack it merges up to the slot's limit, and on another item it
    swaps, if the cursor fits.
  - SWAP takes button 0 to 8 or 40, an `Inventory` index. It swaps that
    index with the slot. A stack too big for the slot leaves the rest at the
    index. When both hold stacks, the slot's stack then goes through
    `Inventory.add`.
  - CLONE needs infinite materials.
  - THROW needs an empty cursor. It drops one (button 0), or the stack.
  - PICKUP_ALL needs a stack on the cursor and an empty slot. It gathers
    from slot 0 forward, or from the end with button 1, in two passes, the
    first skipping full stacks.
- **`moveItemStackTo`**: first merges into stacks of the same item and
  components (only for a stackable item), then puts the rest in the first
  empty slot that takes it, and stops there.
- **`quickMoveStack`**: `ChestMenu`, `HopperMenu` and `ShulkerBoxMenu` move
  a container slot to the player's slots from the end, and a player slot to
  the container's from 0. `DispenserMenu` does the same over 9 slots.
  `InventoryMenu` moves the crafting grid and the armor to slots 9 to 44.
  An armor item goes to its own empty armor slot (8 minus its slot's index:
  the head is 5), and an off-hand item to an empty off hand (45). Otherwise
  slots 9 to 35 go to the hotbar (36 to 44), and the hotbar goes to 9 to 35.
- **Slots**: a slot's limit is the lower of its container's (99) and the
  item's stack size. `ArmorSlot` holds one, and takes only an item whose
  `equippable` slot is its own (`isEquippableInSlot`; `Player` keeps
  `canUseSlot` true for every slot). `ShulkerBoxSlot` refuses a
  `ShulkerBoxBlock` item (`canFitInsideContainerItems`). `tryRemove` from a
  slot that may not take back its own stack gives only the whole stack.
  `BundleItem` overrides a click on or with a bundle, and `Item` and
  `BlockItem` do not.
- `equippable` items limited to some entities (`allowed_entities`) all have
  the `body` or `saddle` slot, never a player's armor slot (the 26.3 item
  component reports).
