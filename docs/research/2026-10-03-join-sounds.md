# A mob's sound in a join window — 2026-10-03

Evidence behind #183: the join-until probe
(`tests/reference/test_observe_until_reference.py`) once had a
`minecraft:sound` in one Instance's join window and not in the other's, in
1 of 20 plays at `repeat.py --stress`. Bytecode was read with `javap` from
the 26.3 server jar. Registry ids were resolved from the data generator's
`registries.json`.

## A mob's sound reaches a player before its chunks — javap

- `Mob.baseTick` plays the mob's ambient sound when
  `random.nextInt(1000) < ambientSoundTime++`, and then resets
  `ambientSoundTime` to minus `getAmbientSoundInterval()` (80 ticks for a
  `Mob`). So when a mob makes a sound is random.
- `Entity.playSound(SoundEvent, float, float)` calls
  `Level.playSound(null, x, y, z, …)`. `ServerLevel.playSeededSound` builds a
  `ClientboundSoundPacket`, a position `sound` and not a `sound_entity`. It
  passes the packet to `PlayerList.broadcast(except, x, y, z,
  SoundEvent.getRange(volume), dimension, packet)`.
- `SoundEvent.getRange(volume)` is the sound's fixed range if it has one, or
  else 16 blocks (16 × volume for a volume above 1).
- `PlayerList.broadcast` sends to every player in `players` that is in the
  same dimension and within that distance. It does not check whether the
  player has been sent the chunks there.
- `PlayerList.placeNewPlayer` adds the player to `players` and calls
  `ServerLevel.addNewPlayer` while it handles the login. The first chunk
  batch is sent later, on a tick.

So a mob within 16 blocks of the spawn can send a joining player a `sound`
before the player's first `chunk_batch_finished`. That puts the sound inside
a join window closed by `observe(until="minecraft:chunk_batch_finished")`,
on whichever Instance the sound happened to fall on.

## Where the mobs come from — javap and live

- **verified (javap)** `ServerChunkCache.tickChunks` spawns the passive
  categories only when the game rule `spawn_mobs` is true and
  `gameTime % 400 == 0`, so every 20 s, near loaded chunks.
- **verified (live)** In a fresh flat world, a joining player's
  `login.entity_id` is 1. So no entity existed before it, and the world
  starts with no mobs.
- **verified (live)** The probe Group played Reference against Reference
  with alice staying 3 s after her window. From play 15 of 25, alice got
  `sound` packets 0.7 to 3.0 s after her login, all outside the window and
  all on one Instance only:

  | Sound (registry id) | Category | Position (blocks) |
  | --- | --- | --- |
  | `minecraft:entity.pig_mini.ambient` (1276) | 6, neutral | about (15.4, -60, 3.5) |
  | `minecraft:entity.pig.step` (1266) | 6, neutral | about (16.1, -60, 2.8) |

  The positions are 15.2 to 15.9 blocks from the spawn at (0.5, -60, 0.5),
  inside the 16-block range. Over the 25 plays, `add_entity` showed 33
  pigs, 10 horses and 4 chickens.
- In 15 plays that ended at the window, no `sound` reached alice. The window
  lasts only the few ticks between the login and the first batch, so a
  sound lands in it rarely, and more often once more mobs have spawned.

## What this means

A window near the spawn that is not narrowed to its own packets can hold a
mob's sound on one Instance only. #183 first cleared the mobs inside the join
probe. Since #200 (ADR-0013), every Adapter starts its server with
`spawn_mobs` false, so the probe no longer clears them.

## Turning spawning off from the first tick — javap, Pumpkin source and live

- **verified (javap)** Vanilla 26.3's `server.properties` has no key for a
  game rule (`DedicatedServerProperties`). The game rules are the saved data
  `minecraft:game_rules`, in `world/data/minecraft/game_rules.dat`.
  `MinecraftServer` loads it with
  `SavedDataStorage.computeIfAbsent(GameRuleMap.TYPE)` when it starts, for a
  new world too. `GameRuleMap.CODEC` maps each rule's registry name
  (`minecraft:spawn_mobs`) to its value, a Byte for a boolean. The
  `GameRules` constructor gives every rule the map leaves out its default.
- **verified (live)** Vanilla's own `game_rules.dat` after
  `gamerule spawn_mobs false` is a gzipped compound
  `{data: {…, "minecraft:spawn_mobs": 0b, …}, DataVersion: 5023}`.
- **verified (source, Pumpkin 4426d11)** `read_game_rules`
  (`pumpkin-world/src/world_info/data_files.rs`) reads the `data` compound of
  the same file, and keeps the default of every rule it leaves out.
  `anvil.rs` prefers that file over `level.dat`. `spawn_mobs` gates both
  natural spawning (`pumpkin/src/world/mod.rs`, the tick's spawn step) and
  the mobs a new chunk generates with (`natural_spawner.rs`).
- **verified (live)** Each Adapter wrote a `game_rules.dat` with only
  `minecraft:spawn_mobs` false (vanilla stamped 5023, Pumpkin 4903). On both
  servers, `gamerule spawn_mobs` answered `false`, and a Bot that stayed 30 s
  at the spawn, over one 400-tick spawn cycle, got no mob's `add_entity`
  (from vanilla only Control's player, from Pumpkin none). Without its own clearing, the join probe then had the
  same window in 40 of 40 plays on two vanilla Instances.
