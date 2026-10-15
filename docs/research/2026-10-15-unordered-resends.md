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
