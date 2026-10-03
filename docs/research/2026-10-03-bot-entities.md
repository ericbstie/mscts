# How a client tracks the entities around it — 2026-10-03

Evidence behind #27's `Bot.entities`. Facts are **verified** with
`scripts/research/javap.py` on the 26.3 client jar unless a line says
otherwise. The entity packet layouts are #20's schemas
(`codec/schemas/play/entities.py`).

## The level holds the entities

- The entities belong to the `ClientLevel`. A play `login` makes a new level.
  A `respawn` makes one only when the dimension changes
  (`ClientPacketListener.handleRespawn`). A respawn in the same dimension
  keeps the level and its entities, and the player keeps its entity id
  (`LocalPlayer.setId` with the old one).
- No `add_entity` comes for the player itself.

## What each packet does

- **`add_entity`** (`handleAddEntity`): `createEntityFromPacket` makes the
  entity, `recreateFromPacket` puts it at the packet's position, and
  `ClientLevel.addEntity` adds it, replacing an entity that already had the id.
  A player whose `player_info_update` has not come is skipped with a warning
  ("Skipping Entity with id").
- **Position codec.** Each entity keeps a base position for move deltas
  (`VecDeltaCodec`). `encode(v)` is `Math.round(v * 4096)`, `decode(n)` is
  `n / 4096.0`. A delta decodes axis by axis: an axis whose delta is 0 keeps
  the base's value exactly, and any other is `decode(encode(base) + delta)`.
- **`move_entity_pos`, `move_entity_pos_rot`** (`handleMoveEntity`): the
  delta decodes against the base, and the base becomes the end of the path.
  A stepped delta decodes each step against the one before it
  (`VecDelta$Stepped.decode`), and the path ends at the last step. The entity
  then moves to that end, interpolated over a few ticks. `move_entity_rot`
  only turns it.
- **`entity_position_sync`** (`handleEntityPositionSync`): the base becomes
  the end of the path, and the entity moves there.
- **`teleport_entity`** (`handleTeleportEntity`,
  `setValuesFromPositionPacket`): `PositionMoveRotation.calculateAbsolute`
  adds each flagged axis to the entity's current position and replaces the
  others. **It leaves the base as it was**, so a later move delta still
  decodes against the base from before the teleport.
- **`set_entity_data`** (`handleSetEntityData`): `assignValues` sets each
  entry's value by its index, and keeps the others.
- **`remove_entities`** (`handleRemoveEntities`): each id is removed.
- A packet for an id the level does not have is ignored.

## Attacking, interacting and respawning

- **Attack** (`Minecraft.startAttack` on an entity hit,
  `MultiPlayerGameMode.attack`): the held slot if it changed
  (`ensureHasSentCarriedItem`), then `attack` with the entity id
  (`ServerboundAttackPacket`: one VarInt). `startAttack` then swings, and
  sends `punch`. An item with a `piercing_weapon` component sends
  `piercingAttack` instead; a fist has none.
- **Interact** (`Minecraft.startUseItem` on an entity hit,
  `MultiPlayerGameMode.interact`): the held slot if it changed, then
  `interact` (`ServerboundInteractPacket`): the entity id (VarInt), the hand
  (`InteractionHand.STREAM_CODEC`, a VarInt id: main 0, off 1), the hit
  location minus the entity's position (`Vec3.LP_STREAM_CODEC`, which is
  `LpVec3`), and `isShiftKeyDown()`, which for a `LocalPlayer` is the sneak
  key (`ClientInput.keyPresses.shift`). A success predicted by the client
  swings without a packet. A result that is neither success nor fail lets
  `startUseItem` go on to `useItem` for the same hand.
- **`LpVec3.write`**: each axis is held to ±1.7179869183E10 (NaN becomes 0).
  If the largest absolute axis is below 3.051944088384301E-5, it writes one
  zero byte. Otherwise the scale is that axis rounded up
  (`Mth.ceilLong`), and each quantum is
  `Math.round((v / scale * 0.5 + 0.5) * 32766)`.
- **Respawn**: the death screen's button sends `client_command`
  PERFORM_RESPAWN (ordinal 0). `handleRespawn` calls
  `setClientLoaded(false)` and `startWaitingForNewLevel`, so the client
  sends `player_loaded` again once its world has loaded, as at the join.
- **The server** (`ServerGamePacketListenerImpl`, server jar):
  - `handleClientCommand` PERFORM_RESPAWN does nothing while the player's
    health is above 0. Otherwise it calls `PlayerList.respawn` and
    `restartClientLoadTimerAfterRespawn`.
  - `PlayerList.respawn` makes a new `ServerPlayer` with the old entity id.
    It sends `respawn`, the teleport, the spawn position, the difficulty,
    the experience, the effects and the level info. Then
    `addRespawnedPlayer` puts the player back in the chunk map, which
    queues its chunks.
  - `handleAttack` and `handleInteract` return at once until the client
    has loaded (`hasClientLoaded`), so attacks after a respawn need
    `player_loaded` first, or the server's timeout.
  - Both refuse an entity out of reach (`isWithinAttackRange` and
    `isWithinEntityInteractionRange`, each with 3.0 to spare) or outside
    the world border. `handleInteract` also sets the player's sneaking
    from the packet.

## A summoned zombie, live

- A zombie in a peaceful world is discarded on its first tick
  (`Mob.checkDespawn`: `isAllowedInPeaceful` is false for it), so a live
  test that summons one boots its own Reference at easy difficulty.
  **verified** (server jar).
- In daylight a zombie catches fire unless its head slot holds an item. A
  damageable item loses durability instead, and an unbreakable one
  (`minecraft:unbreakable`) is not damageable, so nothing changes
  (`Mob.burnUndead`). **verified** (server jar).
- **Verified live** (`tests/reference/test_bot_entities_reference.py`, one
  run): a zombie summoned at (2.5, -60, 0.5) with `NoAI` and an unbreakable
  helmet, two blocks from the Bot, reaches it as one `add_entity` inside the
  summon's window. `Bot.entities.find("zombie", near=...)` returns it at
  exactly that position, with the packet's entity id.

- **Verified live** (`tests/reference/test_bot_entity_actions_reference.py`,
  one run each): the Bot's `attack` on that zombie, two blocks away with an
  empty hand, brings one `damage_event` inside the window. It names the
  zombie, with the Bot's entity id as both the cause and the direct source.
  After Control kills the Bot, `respawn()` returns, and the same attack
  brings the same `damage_event`. Since the server ignores attacks until
  the client has loaded, this shows the server took the `player_loaded`.

## Where a Bot differs from a real client

- The Bot keeps where the server last put each entity: the end of the last
  path, or the teleport's position. The client moves the entity there over
  a few ticks (`moveOrInterpolateTo`), and moves some entities itself
  between packets (`set_entity_motion`, gravity). A relative teleport adds
  to the client's current position, which the Bot takes to be the last one
  the server gave.
- The Bot keeps a player entity whose `player_info_update` has not come.
  Vanilla sends the info first, so this differs only for a server that
  does not.
- The Bot keeps no rotation.
