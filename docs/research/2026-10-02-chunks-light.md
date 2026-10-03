# Chunks and light: what the 26.3 client keeps — 2026-10-02

Evidence behind #22: how the vanilla 26.3 client reads `level_chunk_with_light`
and `light_update`, so that a Comparison can tell two encodings of the same
chunk (network traffic) from two different chunks (gameplay).

Facts are **verified** with `scripts/research/javap.py -v` on the 26.3 client
jar (server jar where a line says so) unless a line says *inferred*. Recorded
payloads: the first chunks of the 2026-09-30 joins (vanilla 26.3, Pumpkin
nightly sha256 `b8382a8a…`) and the vanilla pairs behind #30's comment.

## Layout

`ClientboundLevelChunkWithLightPacket`: chunk x and z (Int each), the chunk
data, then the light data.

The chunk data (`ClientboundLevelChunkPacketData.STREAM_CODEC`):

- **Heightmaps**: `ByteBufCodecs.map(EnumMap::new, Heightmap$Types.STREAM_CODEC,
  LONG_ARRAY)`: a VarInt count, then each type (a VarInt id) and its longs (a
  VarInt count, then the longs). The type ids are 0 `WORLD_SURFACE_WG`,
  1 `WORLD_SURFACE`, 2 `OCEAN_FLOOR_WG`, 3 `OCEAN_FLOOR`, 4 `MOTION_BLOCKING`,
  5 `MOTION_BLOCKING_NO_LEAVES`. An unknown id reads as 0 (`ByIdMap.continuous`,
  `OutOfBoundsStrategy.ZERO`). The server sends the types used by the client
  (1, 4 and 5), collected with `Collectors.toMap` (a `HashMap`), so their order is
  the hash order of the enum constants and can change from one boot to the next.
- **Sections**: `byteArray(2097152)`, a VarInt length and that many bytes, which
  hold the chunk's sections bottom to top (`extractChunkData` writes every section
  and checks that the buffer is full).
- **Block entities**: a list of `BlockEntityInfo`: a Byte packing x (high four
  bits) and z (low four bits) in the chunk, a Short y, the block entity type (a
  VarInt registry id) and `OPTIONAL_COMPOUND_TAG` (an NBT compound, or `TAG_End`
  for none).

A section (`LevelChunkSection.read`): a Short block count, a Short fluid count,
then the block states, then the biomes, each a paletted container.

The light data (`ClientboundLightUpdatePacketData.STREAM_CODEC`): four bit sets
(sky mask, block mask, empty sky mask, empty block mask), then the sky arrays and
the block arrays, each a list of `byteArray(2048)`. A bit set is
`ByteBufCodecs.BIT_SET`: a VarInt length and that many bytes, read with
`BitSet.valueOf(byte[])` and written with `BitSet.toByteArray()` (least significant
byte first, trailing zero bytes dropped). It is not an array of longs, as
`FriendlyByteBuf.readBitSet` would read. `light_update` is two VarInts (chunk x
and z) and the same light data.

The others #22 decodes: `forget_level_chunk` is a chunk position as one Long
(`ChunkPos.pack`: x in the low 32 bits, z in the high 32 bits);
`set_chunk_cache_center` is two VarInts (x, z); `set_chunk_cache_radius` one
VarInt.

## Paletted containers

`PalettedContainer.read` reads a Byte, the bits per entry, and gets a
configuration for it (`Strategy.getConfigurationForBitCount`):

| Bits sent | Block states (`Strategy$1`) | Biomes (`Strategy$2`) |
|---|---|---|
| 0 | one value, no data | one value, no data |
| 1 to 3 | a list palette, 4 bits per entry | a list palette, that many bits |
| 4 | a list palette, 4 bits | the global palette |
| 5 to 8 | a hash palette, that many bits | the global palette |
| 9 and up | the global palette | the global palette |

- The entries are read with the configuration's `bitsInMemory()`, not the bits
  sent. For the global palette that is `Mth.ceillog2` of the size of the
  client's registry (`Strategy.<init>`, `Configuration$Global`), whatever the
  byte says.
- Block states: the client's own block state registry. The 26.3 data generator's
  `blocks.json` (jar sha1 `33680f5f…`) has 35,723 states with ids 0 to 35,722,
  so a direct block container has 16 bits per entry.
- Biomes: the registry the server sent in configuration (`registry_data` for
  `minecraft:worldgen/biome`). Each configuration collects its registries afresh
  (`ClientConfigurationPacketListenerImpl.<init>` makes a new
  `RegistryDataCollector`) and appends the entries of every `registry_data` for a
  registry (`RegistryDataCollector$ContentsCollector.append`: `List.addAll`). Both
  recorded joins send 67 entries, so 7 bits. The
  codec reads one packet at a time and cannot see that registry, so it reads a
  direct biome container at the bits sent. The Comparison reads it again at the
  width of the same Transcript's registry when its data is as long as that width
  takes, as the client does (decided on #22; #122's review, finding 1). With 64
  entries, 7 and 8 bits both take 8 longs, so data sent with a byte of 8 is read
  by the client at 7 bits without error.
- The vanilla server writes the bits of its storage (`PalettedContainer$Data.write`:
  `storage.getBits()`), so for a direct container the byte is the global width.
- The palette: one VarInt for a single value; a VarInt count and that many ids for
  a list or hash palette; nothing for the global palette. A list palette holds at
  most `1 << bits` ids: more overflow its array, and the client fails.
- The data: `readFixedSizeLongArray`, with no length prefix (since 1.21.5). Its
  length is fixed by the width: `ceil(entries / (64 / bits))` longs, entries
  packed from the low bits of each long and never split across two longs
  (`SimpleBitStorage`). A section has 4096 block states and 64 biomes. Entry
  `((y << 4 | z) << 4) | x` is the block at (x, y, z) in the section,
  `((y << 2 | z) << 2) | x` the biome cell (`Strategy.getIndex`).
- An entry that indexes past the palette is not an error when read: the client
  throws only when it looks the entry up (`valueFor`).

## What the client keeps of a chunk

`ClientPacketListener.handleLevelChunkWithLight` calls
`ClientChunkCache.replaceWithPacketData`, then queues the light (below).
`LevelChunk.replaceWithPacketData`:

- clears the chunk's block entities, then reads one section for each section of
  the level (the level's height decides how many; bytes left in the buffer are
  never read);
- keeps each section's block count and fluid count as sent. They are not
  recounted, and `hasOnlyAir()` (a block count of 0) is what the light engine
  is told about the section (`enableChunkLight`);
- sets each heightmap from the `EnumMap`, so their order is not kept, and a type
  sent twice keeps the last value;
- creates each block entity at its position from the block there
  (`getBlockEntity(pos, IMMEDIATE)`), and loads the tag only if there is one and
  the sent type is the block entity's type. A position sent twice is loaded twice,
  the last tag last.

So two chunks that put the same block state and biome at every position, the
same counts, the same heightmaps and the same block entities leave the client
with the same chunk, however their containers are encoded.

## How the client applies light

`handleLevelChunkWithLight` queues, on the client level's light queue:
`applyLightData(x, z, light, false)`, then `enableChunkLight` for the chunk.
`handleLightUpdatePacket` queues `applyLightData(x, z, light, true)`.

`applyLightData` reads the sky layer, then the block layer
(`readSectionList`), then calls `LevelLightEngine.setLightEnabled(pos, true)`.
`readSectionList` walks the light sections: there are two more than the chunk
sections (`getLightSectionCount`), one below and one above the world, starting at
`getMinLightSection()`, one below the lowest section. For light section `i`:

- if the mask has bit `i`, it takes the next array and queues
  `new DataLayer(array.clone())`;
- else if the empty mask has bit `i`, it queues `new DataLayer()`;
- else it does nothing: **a section neither mask names keeps the light the
  client had**.

So the mask wins over the empty mask, bits from the light section count up are
never read, an array is taken only for a mask bit in range (arrays beyond are
never read), and `new DataLayer(byte[])` throws unless the array is 2048 bytes.
Too few arrays end the iterator early, and the client fails.

`queueSectionData` keeps the layer queued; `markNewInconsistencies` stores it
only once the light engine stores light for that section (a section with blocks,
or next to one). `forget_level_chunk` drops the chunk and queues the removal of
every light section (`queueLightRemoval`).

### An empty section against an array of zeros

`new DataLayer()` has no array and a default of 0; `get` answers 0 for every
position, as it does for an array of zeros. Of the client's code that holds a
`DataLayer` (every class of the client jar whose constant pool names it), only
two places tell them apart:

- `SkyLightSectionStorage.repeatFirstLayer` copies a layer with no array as it
  is (`isDefinitelyHomogenous`): the same values either way.
- `SkyLightEngine.setLightEnabled(pos, true)` fills with 15 every stored sky
  layer that `isEmpty()` (no array, default 0), from the section below the
  column's top down to
  `max(getBottomSectionY(), blockToSectionCoord(getHighestLowestSourceY() - 1) + 1)`.
  So an empty sky section in that range becomes full sky light at the next
  `applyLightData` of the chunk (the packet's own layers are still queued when
  its own `setLightEnabled` runs), while an array of zeros stays dark.

On a multiplayer client, `setLightEnabled(pos, true)` is called only from
`applyLightData` (`propagateLightSources` is the server's).

`getHighestLowestSourceY` (`ChunkSkyLightSources`) is the highest of the chunk's
per-column lowest sky light sources. It is never below the world's bottom: a
column with nothing blocking the sky reads as `Integer.MIN_VALUE`
(`extendSourcesBelowWorld`), and then `MIN_VALUE - 1` wraps to `MAX_VALUE`, so
the range is empty. Otherwise the range starts at or above the lowest section of
the world. **The light section below the world is never filled**, so there an
empty sky section and an array of zeros leave the client with the same light,
now and later. No client code tells them apart for block light at all.

### What the servers send

- Vanilla's server sends an array for a stored layer that has one, and an empty
  bit for one that `isEmpty()` (server `ClientboundLightUpdatePacketData.prepareSectionData`).
- The first chunk on vanilla (flat world): sky arrays for light sections 1 and
  2, an empty sky section 0, empty block sections 0 to 2, the rest not named.
- #30's vanilla pairs (chunks -1 -1, -1 0, -2 -1 of two Instances): the only
  difference is light section 0, the one below the world: one Instance sent it as
  an empty sky section, the other as an array of 2048 zero bytes (7,259 against
  9,308 bytes).
- Pumpkin's first chunk: sky arrays for light sections 1 to 24, empty sky
  sections 0 and 25, and every section, 0 to 25, as empty block light.

## Rules for the Comparison

Each light section is compared as the client reads it: an array, empty, or not
sent. These are equal:

- a mask bit and the same mask bit plus an empty bit (the mask wins);
- bits past the light section count, and arrays past the mask's bits, against
  none (never read);
- for block light, an empty section and an array of 2048 zero bytes;
- for sky light, in light section 0 only (below the world), an empty section and
  an array of zeros.

A `light_update` does not say how high its level is. No level has more than 256
light sections: `DimensionType` reads `height` with `Codec.intRange(16, Y_SIZE)`,
and `Y_SIZE` is `(1 << BlockPos.PACKED_Y_LENGTH) - 32`, where `PACKED_Y_LENGTH`
is `64 - 2 * 26` (`PACKED_HORIZONTAL_LENGTH` is `1 + log2` of the power of two
above 30,000,000). So a level is at most 4,064 blocks, 254 sections, high.

Everything else stays different. Not sending a section is not the same as
sending it empty, since the client keeps what it had. Pumpkin's explicit sky
arrays where vanilla names no section change what the client stores once those
sections hold light, so they are a gameplay difference, not an encoding.

## Chunk order and batches

(Server `PlayerChunkSender`.) `sendNextChunks` sends `chunk_batch_start`, then
each chunk (`sendChunk`: the `level_chunk_with_light`, then
`LevelDebugSynchronizers.startTrackingChunk`, which returns at once while no
client subscribes to debug values), then `chunk_batch_finished`, all in one call
on the server thread. The chunks come nearest first
(`ChunkPos.distanceSquared`), from the `LongOpenHashSet` of pending chunks:
sorted, or `Comparators.least` when more are pending than the batch takes.
Chunks at the same distance come in the set's iteration order, which can differ
from one play to the next. In both recorded joins, nothing the server thread
sends came between a batch's chunks. A play `pong_response` can: the server
answers a ping from the network thread (#122's ordering review).

Which chunks a batch holds also races: `sendNextChunks` takes only the chunks
that are ready, and readiness depends on the worker threads. Under load, two
vanilla Instances with the same chunk centre split the same chunks into other
batches (#122's ordering review, finding 2).

The light updates of one tick go out in the order of
`ServerChunkCache.chunkHoldersToBroadcast`, a `ReferenceOpenHashSet`, so their
order across chunks is an identity hash order (#122's ordering review). That
light for different chunks has the same effect in either order is *inferred*:
each update is queued for its own position.

### What the client does with each packet

- `level_chunk_with_light`, `light_update` and `forget_level_chunk` act on the
  chunk at their position: `ClientChunkCache.replaceWithPacketData` and the
  light queue, `ClientLevel.queueLightUpdate`, `ClientChunkCache.drop` with
  `queueLightRemoval`. So their order matters for one position.
- `chunk_batch_start` and `chunk_batch_finished` feed only
  `ChunkBatchSizeCalculator` (`onBatchStart`, `onBatchFinished(batchSize)`,
  then `chunk_batch_received` with `getDesiredChunksPerTick`), on the network
  thread. They do not change the world, and `batch_size` only sets the rate the
  client asks the server for.
- `keep_alive` is answered; `set_time` sets the clock
  (`ClientLevel.setTimeFromServer`, `ClientClockManager.handleUpdates`);
  `award_stats` sets stats; `pong_response` goes to `PingDebugMonitor`. None
  reads a chunk.
- `add_entity` (`Entity.recreateFromPacket`, `ClientLevel.addEntity`), the
  `move_entity_*` packets (`Entity.moveOrInterpolateTo`), `rotate_head`,
  `set_entity_motion`, `update_attributes` and `remove_entities` set the
  entity's fields. Whether its chunk is loaded decides only whether it ticks:
  `TransientEntitySectionManager.addEntity` takes a section's status from the
  ticking chunks, and `startTicking` / `stopTicking` update the sections that
  exist, so either order ends the same. One exception (#122's re-review): a
  `move_entity_*` handler ends in `Entity.setOnGround`, whose
  `checkSupportingBlock` reads the blocks under the entity
  (`Level.findSupportingBlock`). It only sets the block the entity stands on
  until it next moves. The rule below still treats these packets as reading no
  chunk: ending runs there would bring back false mismatches where two vanilla
  servers split chunks into batches differently. That trade-off is accepted.
- `entity_position_sync` and `teleport_entity` call `ClientLevel.isTickingEntity`:
  the entity snaps or moves smoothly depending on whether its chunk is loaded.
- `set_entity_data` can read a block: `LivingEntity.onSyncedDataUpdated`, on the
  client, calls `setPosToBed`, which reads `level().getBlockState` at the bed.
  Of the 39 `onSyncedDataUpdated` overrides in the client's entity and player
  classes, this is the only one that reads the world.
- `entity_event` (`Entity.handleEntityEvent`, one override for each kind) is not
  traced.

In six pairs of live vanilla joins (49 chunks each, in 4 to 10 batches), only
`update_attributes` and `set_time` came between batches, and entity bundles came
after the last chunk. With the same chunk centre, the rule below left no chunk
missing or unexpected; with another centre (a random spawn), one row of the 7x7
chunks differed, as it should.

### The rule

A *run* is the packets between two that are neither chunk packets nor among
those treated as reading no chunk (the batch packets, the heartbeat packets,
`pong_response`, `bundle_delimiter` and the entity packets above that set
fields). Each run becomes its chunk packets, sorted stably by position, then its
other packets in their order, so such a packet lands in the same place whether
it came before the run's first chunk or after it. Runs are found in the
Bot's whole stream, before windows or Masks leave anything out. So a chunk never
moves across a packet for its own position, nor across any packet whose effect
can depend on the order (`entity_position_sync`, `teleport_entity`,
`set_entity_data`, `entity_event`, or anything not in the list). Batch packets
only one side sent, and another `batch_size`, are network traffic.
