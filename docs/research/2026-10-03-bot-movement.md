# What a moving client sends — 2026-10-03

Evidence behind #25 (`Bot.move`, `look`, `sprint`, `sneak`, `jump`, `tick`).
Facts are **verified** with `scripts/research/javap.py` on the 26.3 client or
server jar unless a line says otherwise. The wiki (revision 3810839) agrees on
every layout.

## Layouts

- `ServerboundMovePlayerPacket.packFlags`: bit 0 on ground, bit 1 horizontal
  collision, written as one byte (`readUnsignedByte` back). `Pos` is three
  Doubles and the flags; `PosRot` three Doubles, yaw and pitch as Floats, the
  flags; `Rot` the two Floats and the flags; `StatusOnly` the flags.
- `Input`'s stream codec writes one byte: forward 1, backward 2, left 4,
  right 8, jump 16, shift 32, sprint 64. `KeyboardInput` sets each from its
  key being down, so the sprint bit is the sprint key, not sprinting.
- `ServerboundPlayerCommandPacket`: VarInt entity id, the action by
  `writeEnum`, VarInt data (0 from the two-argument constructor). `Action`
  has 7 constants: STOP_SLEEPING 0, START_SPRINTING 1, STOP_SPRINTING 2,
  START_RIDING_JUMP 3, STOP_RIDING_JUMP 4, OPEN_INVENTORY 5,
  START_FALL_FLYING 6. The client sends its own entity id.
- `ServerboundClientTickEndPacket`: `StreamCodec.unit`, no fields.

## What the client sends on a tick, and in what order

- `Minecraft.tick` calls `LocalPlayer.sendChanges` (after the level's
  entities tick), and ends with `client_tick_end` whenever it has a
  connection and is not paused.
- `sendChanges` (once the client has loaded) sends `player_input` if the keys
  differ from `lastSentInput`, then, for a player not riding, `sendPosition`.
- `sendPosition` first sends a sprint command if `isSprinting()` differs from
  `wasSprinting`, then picks one movement packet:
  - it adds one to `positionReminder`;
  - the position counts as moved if `Mth.lengthSquared` of the change since
    `xLast`, `yLast`, `zLast` is above `Mth.square(2.0E-4)`, or if
    `positionReminder` has reached 20 (`POSITION_REMINDER_INTERVAL`);
  - the rotation counts as changed if yaw or pitch differs from `yRotLast` or
    `xRotLast` (a float subtraction compared with 0);
  - both: `move_player_pos_rot`; one: `move_player_pos` or
    `move_player_rot`; neither, but on ground or horizontal collision changed:
    `move_player_status_only`; else nothing;
  - it then keeps the position (and resets the reminder to 0) only if it was
    sent, the rotation only if it was sent, and on ground and horizontal
    collision always.
- A fresh `LocalPlayer` starts with all of these at 0 or false, and
  `MultiPlayerGameMode.createPlayer` gives it `Input.EMPTY` and not sprinting.
  So its first tick after a join sends the position, and the rotation unless
  it is yaw 0 and pitch 0.
- `ClientPacketListener.handleMovePlayer` applies a `player_position` and
  sends only `accept_teleportation`. It changes none of the values above, so
  the next tick reports the corrected position, which differs from the last
  one sent.
- `PositionMoveRotation.calculateAbsolute` clamps pitch to -90..90 before
  `Entity.setXRot`, which ignores a non-finite value and clamps again after
  `% 360`. `setYRot` ignores a non-finite value and keeps any other as it is.

## What the server does with it

- `ServerGamePacketListenerImpl.handleMovePlayer`: a packet with a position
  while `receivedPositionThisTick` is set disconnects the player with
  `multiplayer.disconnect.invalid_player_movement`. Only
  `handleClientTickEnd` clears it. **Verified live** (a fresh Reference,
  2026-10-03): two `move_player_pos` each followed by `client_tick_end`, sent
  back to back, were accepted; two with no `client_tick_end` between were
  answered with that disconnect.
- The speed check measures from `firstGood*`, which `tickPlayer` resets at the
  start of every tick (`resetPosition`). A move is too quick when its squared
  length minus the squared velocity is above 100 (300 when gliding) times the
  move packets since the last tick (1 past 5). The server then logs
  `moved too quickly!` and teleports the player back to where it has it,
  with an absolute `player_position`. It runs only with the game rule
  `player_movement_check` on, its default.
- `handleClientTickEnd` sets the player's known movement to zero only when
  no movement packet came in that client tick (`receivedMovementThisTick`).
  So the server takes the player to be still moving at its last step until
  a client tick without one, which for a Bot is `tick()` after its last
  move.
- `handlePlayerInput` keeps the input and, once the client has loaded, sets
  the shift key from it. `handlePlayerCommand` ignores everything until the
  client has loaded; START_SPRINTING and STOP_SPRINTING set sprinting.

## The order a Bot relies on

- One call is one client tick: the keys, the sprint command, the movement
  packet and `client_tick_end`, in that order, sent at once. A Bot sends no
  tick on its own, so a second position never arrives in one client tick.
- The Bot answers a `player_position` from its reader, as soon as it arrives,
  while a Group's call may be sending its tick. So `accept_teleportation` can
  come between the packets of one scripted tick, and a move computed before
  the correction arrived can reach the server after it. Vanilla's client
  handles packets at the start of its tick, before `sendChanges`, so its
  accept never splits a tick; over a slow link its move can still cross the
  correction in the same way. The server ignores a move while it awaits the
  accept (`updateAwaitingTeleport`), taking only its rotation.
- A Group that moves once per server tick awaits `Bot.sync` between moves: the
  barrier ends after a server tick has passed, so each move is measured from
  a fresh `firstGood*`.
- **Verified live** (`tests/reference/test_bot_move_reference.py`): a Bot put
  at (0.5, -60, 0.5) by Control walks 25 steps of 0.2 blocks, one per server
  tick, with no `player_position` back; then a move 20 blocks up in one packet
  gets an absolute `player_position` back to where it stood.

## Sprinting

- `LocalPlayer.canStartSprinting` needs `hasForwardImpulse`, sprinting to be
  possible (not mobility-restricted, enough food or flying, not in shallow
  water), not `isSlowDueToUsingItem`, and not `isMovingSlowly` (crouching or
  crawling) unless under water. `shouldStopRunSprinting` stops sprinting once
  the forward impulse goes. Crouching alone does not stop a sprint already
  started. So no 26.3 client sends START_SPRINTING without holding forward.
  A Bot that sprints holds forward and sprint (`0x41`), and refuses to start
  while it sneaks.

## Where a Bot differs from a real client

- A real client ticks every 50 ms whether or not its player does anything,
  so it sends `client_tick_end` every 50 ms and reports its position again
  every 20 ticks (one second) when idle. A Bot counts its calls instead: it
  sends a tick only when a Group calls, and the 20-tick reminder comes on the
  20th call without a position.
- A real client that moves sideways holds the keys that move it. A Bot's
  `move` holds no key: the Group gives the position, and `player_input`
  reports only what `sprint`, `sneak` and `jump` hold.
- A Bot does not know its food level, whether it uses an item, or whether it
  is under water, so it does not refuse a sprint that those would stop.
- A second play `login`, or a `respawn`, makes a new `LocalPlayer`
  (`ClientPacketListener.handleLogin`, `handleRespawn`): its last reported
  position, rotation, reminder and on-ground start fresh, and its last sent
  input and sprinting too unless the respawn keeps entity data
  (`data_kept` bit 1, `KEEP_ENTITY_DATA`). A Bot does the same. After a
  respawn the real client sends nothing from `sendChanges` until it has
  loaded again and sent `player_loaded`, and its new player is not
  sprinting. A Bot sends no `player_loaded` after a respawn and keeps the
  keys and sprinting its Group set.
