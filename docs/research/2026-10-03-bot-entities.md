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
