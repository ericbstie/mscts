# Orders the client does not keep: section blocks and tick-end resends — 2026-10-15

Evidence behind #320. Bytecode was read with `javap` from the 26.3 client
and server jars (`scripts/research/javap.py`).

## `section_blocks_update.blocks` — javap

- Server: `ChunkHolder.broadcastChanges` builds the packet from the
  section's changed positions, a `ShortOpenHashSet`, in its iteration
  order (docs/research/2026-10-03-blocks-fill-under-load.md). Another
  server can send the same changes in another order.
- Client: `ClientboundSectionBlocksUpdatePacket` reads the positions and
  states into two arrays in order, and `runUpdates` walks them in order.
  `ClientPacketListener.handleChunkBlocksUpdate` gives each to
  `ClientLevel.setServerVerifiedBlockState(pos, state, 19)`, which calls
  `Level.setBlock(pos, state, 19, 512)` unless a block prediction holds
  the position.
- `Level.setBlock` sets the block in its chunk, marks it dirty and tells
  the renderer (flag 2). Flag 1 calls `updateNeighborsAt`, and
  `Level.updateNeighborsAt(BlockPos, Block, Orientation)` is an empty
  method that `ClientLevel` does not override. Flag 16 skips the shape
  updates. So each change sets only the block at its own position: blocks
  at different positions can come in any order, and a position sent twice
  ends with its last state.

## Tick-end entity resends — javap

- Server: `ChunkMap.<init>` makes `entityMap` an `Int2ObjectOpenHashMap`
  keyed by the raw entity id. `ChunkMap.tick` first runs
  `updateChunkTracking` for each player, then walks
  `entityMap.values()`: for an entity whose section changed it runs
  `TrackedEntity.updatePlayers` (an `add_entity` bundle or
  `remove_entities`), and for one that changed section, needs a sync or
  is in entity-ticking range it runs `ServerEntity.sendChanges`.
- `ServerEntity.sendChanges` can send `set_passengers`, a map's data,
  `move_entity_rot`, a move packet (`move_entity_pos`,
  `move_entity_pos_rot` or `entity_position_sync`), `move_minecart_along_track`,
  `set_entity_motion` (or a bundle of it with `projectile_power`),
  `rotate_head`, and through `sendDirtyEntityData` `set_entity_data` and
  `update_attributes`. So the resends of several entities in one tick
  come in the hash order of their raw ids, which differ between
  Instances (#35: 17 of 20 plays with 4 drops did not match).
- Client: `ClientPacketListener.handleSetEntityData`
  (`getEntity`, `SynchedEntityData.assignValues`),
  `handleSetEntityMotion` (`lerpMotion`), `handleUpdateAttributes`
  (the entity's `AttributeMap`), `handleRotateMob` (`lerpHeadTo`),
  `handleMoveEntity` (`moveOrInterpolateTo`, `setOnGround`) and
  `handleEntityPositionSync` (`moveOrInterpolateTo` or `snapTo`, and
  `positionRider` when the local player rides it) each act on the entity
  the packet's id names. So resends for different entities can come in
  any order. Those for one entity are applied in turn and keep their
  order. `set_passengers` names two entities and is left out.
- What bounds a tick: a Transcript records no tick ends, except the tick
  Marks of a tick-exact Group. There each packet's tick is compared on its
  own, so a run of resends needs no tick bound.
