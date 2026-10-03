# What a client sends to dig, place and use items — 2026-10-03

Evidence behind #26 (`Bot.hold`, `dig`, `stop_digging`, `cancel_digging`,
`place`, `use_item`, `release_item`, `swing`). Facts are **verified** with
`scripts/research/javap.py` on the 26.3 client or server jar unless a line
says otherwise. The wiki is revision 3810839.

## Layouts

- `player_action`: the action by `writeEnum` (VarInt), the block
  (`writeBlockPos`), the face as one byte (`get3DDataValue`; read back with
  `readUnsignedByte` and `Direction.from3DDataValue`, which takes any value),
  and a VarInt sequence. `Action` has **9** constants: START_DESTROY_BLOCK 0,
  CHANGE_DESTROY_DIRECTION 1, ABORT_DESTROY_BLOCK 2, STOP_DESTROY_BLOCK 3,
  DROP_ALL_ITEMS 4, DROP_ITEM 5, RELEASE_USE_ITEM 6, SWAP_ITEM_WITH_OFFHAND 7,
  STAB 8. **The wiki lists 8**, without CHANGE_DESTROY_DIRECTION, so it gives
  every later action one less. The jar is right; the live test sends STOP as 3.
- `use_item_on`: the hand (`InteractionHand.STREAM_CODEC`, an `idMapper`
  VarInt, out of range reads as the main hand), the block hit
  (`BlockHitResult.STREAM_CODEC`: block, face as an `idMapper` VarInt that
  wraps, the hit point less the block as three Floats, inside block, world
  border hit), a VarInt sequence.
- `use_item`: hand (VarInt), sequence (VarInt), yaw and pitch (Floats).
- `set_carried_item`: the slot as a Short.
- `punch`: no fields (`StreamCodec.unit`). 26.3 has no swing packet with a
  hand: the server's `handlePunch` swings the main hand.
- `block_changed_ack` (clientbound): a VarInt sequence.
- `set_held_slot` (clientbound): a VarInt slot. The client takes it only if
  it is a hotbar slot, 0 to 8 (`Inventory.isHotbarSlot`).
- Faces (`get3DDataValue`): down 0, up 1, north 2, south 3, west 4, east 5.

## What the client sends, and in what order

- `Minecraft.tick` runs `MultiPlayerGameMode.tick`, then `handleKeybinds`
  (attack, use, hotbar keys), then the level's entities (the player's
  `sendChanges`), then `client_tick_end`.
- `ensureHasSentCarriedItem` sends `set_carried_item` when the selected slot
  differs from `carriedIndex`, which starts at 0. `MultiPlayerGameMode.tick`
  calls it, and so does every action below before it sends. So a hotbar key
  pressed on one tick is sent at the start of the next, or just before an
  action on the same tick.
- `handleSetHeldSlot` selects the slot but leaves `carriedIndex`, so the
  next tick sends the slot back.
- `BlockStatePredictionHandler.startPredicting` adds 1 to the sequence, and
  the predicted packet carries the new value: the first is 1. The handler
  belongs to the `ClientLevel`, which is new with each play `login`, and
  with a `respawn` only if the dimension changes.
- Attack on a block (`startAttack`): `startDestroyBlock` sends START,
  predicted (in survival, an ABORT of a different block being broken comes
  first). Then the swing sends `punch`.
- Attack held (`continueAttack(true)`): `continueDestroyBlock` adds the
  block's progress each tick. It sends CHANGE_DESTROY_DIRECTION (sequence
  0) if the face changed, and STOP, predicted, on the tick the progress
  reaches 1. While it returns true, which it does on the finishing tick,
  the swing sends `punch`.
- Attack let go (`continueAttack(false)`): `stopDestroyBlock` sends ABORT
  for the block being broken, face down, sequence 0. No `punch`.
- Use on a block (`useItemOn`): `use_item_on`, predicted. The swing for a
  success is the client's own, and sends nothing. If the result is neither
  success nor fail, `startUseItem` goes on to `useItem` for the same hand,
  and tries the off hand after the main one.
- Use (`useItem`): `use_item`, predicted, with the player's yaw and pitch.
  No movement packet comes first in 26.3.
- Release (`releaseUsingItem`): RELEASE_USE_ITEM at 0, 0, 0, face down,
  sequence 0.

## What the server does with it

- Each predicted action's sequence is acknowledged with `block_changed_ack`
  at the end of the tick, one packet for the highest sequence of the tick:
  `ServerGamePacketListenerImpl.tick` sends it, from `tickConnection`.
- A block that breaks or is placed reaches the player with the tick's
  changes (`ServerLevel.tick` broadcasts them, before `tickConnection`).
  `Connection.tick` flushes after the listener's tick, so the change and the
  ack go out together. `handleUseItemOn` also sends the clicked block and
  the block on the clicked face at once, in the packet phase, so a placed
  block comes twice: at once, then with the tick's changes.
- **Verified live**, 270 creative digs (120 on a quiet machine, 150 under
  `scripts/repeat.py --stress`), each closed by `Bot.sync`: the ack came
  right after the `block_update`, in the same read, every time, and inside
  the barrier every time.
- **Verified live** (`tests/reference/test_bot_blocks_reference.py`): in
  creative, START on the grass two blocks from the player sets air there
  (`block_update`) and acknowledges sequence 1. `use_item_on` with stone
  held, on the top of the block below, puts stone (state 1) there, sent
  twice, and acknowledges 2. In survival, START then STOP on stone in the
  same client burst leaves the stone, sends no `block_update`, and
  acknowledges up to 4.
- A STOP before the block's progress reaches 0.7 does not break it, and
  sends nothing back. `ServerPlayerGameMode` keeps it as a delayed break
  (`hasDelayedDestroy`), which its own tick goes on with, and breaks the
  block once the progress reaches 1.

## Reading a window by time

`Transcript.record` keeps `events` in arrival order (`bisect.insort`). A Bot
records a packet when it takes it, so a packet Control takes later, stamped
earlier, goes into the middle of `events`. A window taken as a range of
`events` indexes then shifts, and loses its last packets. The first run of
the live test closed each window at `len(transcript.events)` and lost the
dig's ack, while the `block_update` just before it stayed in.

**Verified live**: 40 creative digs, each closed by `Bot.sync`, with Control
taking its packets only at its next command. The index window lost the ack
in 14 of them, and a window by time lost it in none. Control's copies of
the dig (`level_event`, `swing_animation`, `block_update`) were the packets
put in. The live test now reads Observation windows by their Marks' times,
as Compare does.

## Where a Bot differs from a real client

- One call is one client tick, as for movement. `hold` sends the slot on its
  own tick, which is the tick after a real client's key press.
- The Bot does not time breaking. A Group calls `swing` on each tick the
  client would, and `stop_digging` on the tick it tests.
- `place` sends `use_item_on` only: the Bot cannot tell that the use did
  nothing, so it never goes on to `use_item`.
- A respawn makes a new player with a new inventory. The Bot keeps the
  selected and last sent slots across one.
