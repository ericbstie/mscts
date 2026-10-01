# Block and world event packets — 2026-10-01

Facts behind the block and world event schemas (issue #29): the layout of each
packet, where the sound seed comes from, and payloads recorded from vanilla
26.3 (the Reference). Two kinds of fact:

- **verified (javap)**: read from the 26.3 server jar
  (`META-INF/versions/26.3/server-26.3.jar` inside the bundler `server.jar`,
  sha1 `33680f5f…`) with `scripts/research/layout.py` on each packet's
  `STREAM_CODEC`, and `scripts/research/javap.py` for the rest;
- **verified (live)**: observed against the Reference, an operator Bot sending
  one command at a time and taking every clientbound play packet until a
  barrier (two stats round trips).

The wiki is `Java_Edition_protocol/Packets`, revision 3799543 (2026-09-27,
"26.3, protocol 777"), raw wikitext. It agrees with the jar on all eleven
layouts. The jar wins wherever they could differ.

## Layouts

All clientbound, play state. `Pos` is `BlockPos.STREAM_CODEC`, a Long (`POSITION`).
`State` is `idMapper(Block.BLOCK_STATE_REGISTRY)`, a plain VarInt block state
id. `Sound` is `SoundEvent.STREAM_CODEC` (`shapes.SOUND_EVENT`). `Particle` is
`ParticleTypes.STREAM_CODEC` (`particles.PARTICLE`).

| Packet (wiki name) | Fields, in order | Notes |
| --- | --- | --- |
| `block_update` (Block Update) | Pos, State | |
| `section_blocks_update` (Update Section Blocks) | SectionPos (Long), VarInt count, count × VarLong | each VarLong is the state id `<< 12` OR the section-relative position `x << 8 \| z << 4 \| y` |
| `block_entity_data` (Block Entity Data) | Pos, VarInt block entity type, compound tag | `ByteBufCodecs.TRUSTED_COMPOUND_TAG` is `COMPOUND_TAG` with another quota: the root must be a compound, so `shapes.COMPOUND_TAG` fits. The wiki says only "NBT" |
| `block_event` (Block Action) | Pos, Unsigned Byte, Unsigned Byte, VarInt block | the block is a registry id (not a state) and comes **last** |
| `block_destruction` (Set Block Destroy Stage) | VarInt entity id, Pos, Unsigned Byte stage | |
| `level_event` (World Event) | Int event, Pos, Int data, Bool global | |
| `sound` (Sound Effect) | Sound, VarInt category, Int x, Int y, Int z, Float volume, Float pitch, Long seed | x, y and z are the position times 8 (`getX` divides by 8.0) |
| `sound_entity` (Entity Sound Effect) | Sound, VarInt category, VarInt entity id, Float volume, Float pitch, Long seed | |
| `level_particles` (Particle) | Particle, Bool override limiter, Bool always show, Double x, y, z, Float x, y, z distance, Float x, y, z max speed, VarInt count, VarInt randomization type | the 26.3 record has the options inside the particle, and the randomization type at the end |
| `explode` (Explosion) | 3 × Double centre, Float radius, Int block count, Bool then 3 × Double player knockback, Particle, Sound, VarInt count then count × (Particle, Float scaling, Float speed, VarInt weight), Bool play sound | the block particle list is `WeightedList.streamCodec(ExplosionParticleInfo.STREAM_CODEC)`: `ByteBufCodecs.list()` over a `Weighted` (the value, then a VarInt weight) |
| `game_event` (Game Event) | Unsigned Byte event, Float value | the event ids are 0 to 13 (`ClientboundGameEventPacket$Type`); an unknown id reads as a null event (`Int2ObjectMap.get`), so the packet itself does not fail |

Facts that decide a strict decoder:

- **verified (javap)** `SectionPos.STREAM_CODEC` is `LONG.map(SectionPos::of,
  SectionPos::asLong)`. `asLong` is `(x & 0x3FFFFF) << 42 | (y & 0xFFFFF) |
  (z & 0x3FFFFF) << 20`, and `x`, `y`, `z` read back signed: `l >> 42`,
  `l << 44 >> 44`, `l << 22 >> 42`.
- **verified (javap)** A section entry reads as `positions[i] = (short)(l &
  4095)` and `state = BLOCK_STATE_REGISTRY.byId((int)(l >>> 12))`. The relative
  position decodes as `x = (s >>> 8) & 15`, `y = s & 15`, `z = (s >>> 4) & 15`.
  The writer sends `((long) Block.getId(state) << 12) | positions[i]`, so a
  value outside 0 to 2^43 - 1 is no entry vanilla sends (the `(int)` cast would
  drop the high bits, and a block state id is never negative).
- **verified (javap)** The sound category is `FriendlyByteBuf.readEnum`:
  `getEnumConstants()[readVarInt()]`, so an ordinal outside 0 to 10 throws on
  the client. `SoundSource` has 11 values: master 0, music 1, records 2,
  weather 3, blocks 4, hostile 5, neutral 6, players 7, ambient 8, voice 9, ui
  10. This is not `shapes.ENUM` (an `idMapper`, which answers an out-of-range id
  with a default).
- **verified (javap)** The particle randomization type is an `idMapper` over
  `ByIdMap.continuous(.., ZERO)`: a plain VarInt, and an out-of-range id reads
  as the default (so `shapes.ENUM` fits).
- **verified (javap)** `ClientboundExplodePacket` in 26.3 has no seed and no
  random field. `ServerLevel.explode` sends it to every player within 64
  blocks (4096 squared), with that player's own knockback.

## The sound seed

**verified (javap)** The seed of `sound` and `sound_entity` is drawn at random
by the server, from a generator that no world setting seeds:

- `Level.soundSeedGenerator` is `RandomSource.createThreadSafe()`, a
  `ThreadSafeLegacyRandomSource(RandomSupport.generateUniqueSeed())`, and
  `generateUniqueSeed()` is a uniquifier `XOR System.nanoTime()`. `Level.random`
  is `RandomSource.create()`, seeded the same way. Neither is the world seed.
- `Level.playSound` (all four overloads, the position and the entity ones)
  calls `playSeededSound(.., soundSeedGenerator.nextLong())`. `PlaySoundCommand`,
  `PlayerList.respawn`, `Raid` and `RaidCommand` draw from `Level.random`.
  `ServerLevel.playSeededSound` puts the seed in a `ClientboundSoundPacket` or
  a `ClientboundSoundEntityPacket`.

**verified (live)** Two vanilla runs, and two calls in one run, send different
seeds for the same sound:

| Sound | Run 1 seed | Run 2 seed |
| --- | --- | --- |
| note block (harp, powered by a redstone block) | 3208859991703385433 | -2498270536482869670 |
| door (powered by a redstone block) | -3210500971036782204 | -8370141963708639115 |
| `playsound minecraft:block.note_block.harp` | -7325282947829501054 then 2423340108416094125 | 7725919872382189622 then -4600362933739800704 |

So the seed is a field vanilla draws at random each run: an exact Group never
compares it, and a statistical Group compares its distribution (ADR-0006 forbids
masking what a player can hear; the seed picks a variant of the sound the player
hears, and every seed is as valid as another).

Also **verified (live)**: the pitch of a powered door's `sound` is random too
(`DoorBlock` plays it at `nextFloat() * 0.1 + 0.9`): 0.9715679883956909 in run
1 and 0.9713852405548096 in run 2. A note block's pitch (0.5 for the lowest
note) and a command's are not random. That is a random value in a field that is
fixed for other sounds, so it is not in the Comparison's table of random
fields (a per-field table cannot say "random only for doors").

`sound_entity` comes from mob behaviour (`LongJumpMidJump`, `RamTarget`, the
frog's tongue, the allay, shearing a sheep or a mooshroom), not from a command,
so no command makes vanilla send one.

## What a command makes vanilla send

**verified (live)**, an operator Bot in the default flat world (the surface is
at y -61, so -60 is the first free block):

| Command | Packets (besides entities, time and chat) |
| --- | --- |
| `setblock 1 -60 1 minecraft:stone` | `block_update` |
| `fill 2 -60 2 3 -59 3 minecraft:stone` (8 blocks, one section) | `section_blocks_update` |
| `setblock 8 -60 8 minecraft:note_block`, then a `redstone_block` next to it | `block_update`; then `section_blocks_update`, `block_event`, `sound` |
| an `oak_door` (both halves), then a `redstone_block` next to it | `section_blocks_update`; then `sound`, `section_blocks_update` |
| `setblock … minecraft:spawner`, `minecraft:oak_sign` | `block_update`, `block_entity_data` |
| `data merge block … {front_text:…}` on a sign | `block_update`, `block_entity_data` |
| `setblock 1 -60 1 minecraft:air destroy` | `level_event` (2001, the broken block's state), `block_update` |
| `particle …` | `level_particles` |
| `weather rain` | `game_event` 7 (rain level change) once a tick, its value rising by about 0.01 |
| `gamemode creative` | `game_event` 3 (change game mode), value 1.0 (survival is 0.0) |
| `summon tnt` with `fuse:1`, 3 blocks from the Bot | `explode`, `section_blocks_update` |

No command makes vanilla send `block_destruction` (another player's dig) or
`sound_entity` (above), so those two are pinned with payloads built from the
layouts.

The recorded payloads are in `tests/codec/schemas/test_play_blocks.py` and
`test_play_world_events.py`, each named for the command that caused it.
