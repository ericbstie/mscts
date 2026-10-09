# How vanilla hurts a player in the world: fall, drowning, fire, suffocation, the void, freezing — 2026-10-09

Evidence for #56. Facts are **verified** with `scripts/research/javap.py` on the 26.3 server jar
unless a line says *live* (two vanilla 26.3 Instances, 2026-10-09).

## Time

- A player ticks in a frozen world: `TickRateManager.isEntityFrozen` is false for a `Player`. Air,
  fire and freezing run in real time, so the Groups end a window on the `set_health` they wait for
  instead of stepping. Only what a packet drives (a move) is stepped.
- `ServerPlayer.isInvulnerableTo` is true only while the player has not sent `player_loaded`. There
  is no spawn protection.

## Damage

- Fall: `ServerGamePacketListenerImpl` calls `ServerPlayer.doCheckFallDamage(dx, dy, dz, onGround)`
  for each move. `Entity.checkFallDamage` adds -dy to the fall distance unless the player is in
  water, and on ground with a distance above 0 calls `Block.fallOn` and resets it. `HayBlock.fallOn`
  multiplies by 0.2, `SlimeBlock` by 0 unless the player sneaks. 23 blocks onto stone is 20
  damage, which kills. The rules are `fall_damage`, `drowning_damage`, `fire_damage` and
  `freeze_damage`.
- Drowning: `LivingEntity.baseTick`, with the eyes in water, lowers the air; at -20 it resets it to
  0, broadcasts entity event 67 and hurts for 2. With `drowning_damage` off the event still comes.
- Void: `Entity.checkBelowWorld` hurts for 4 below minY - 64, y -128, each tick.
- Suffocation: `LivingEntity.baseTick` hurts for 1 when `isInWall`.
- Freezing: `LivingEntity.aiStep` hurts for 1 when `tickCount % 40 == 0` and the player is fully
  frozen. `PlayerList.respawn` builds a new `ServerPlayer`, so `tickCount` starts at the respawn
  `_fresh` makes, and the ticks before the first hit are timing.
- Order in a tick: `damage_event`, `set_entity_data` (health, index 9), `set_health`. The damaged
  player does not get the sound of its own damage (*live*).

- Death: `ClientboundPlayerCombatKillPacket.STREAM_CODEC` is a VarInt `playerId` then the message
  (`ComponentSerialization.TRUSTED_STREAM_CODEC`, network NBT). The player id differs between
  plays on one server, because the entity counter does: 19 of 20 fall plays differed in the raw
  bytes until the packet was decoded, and the id numbered like any other (*live*, Self-check).

## Sounds

- `Entity.lavaHurt` plays GENERIC_BURN at volume 0.4 with pitch 2.0 + `nextFloat()` * 0.4.
- `Entity.playEntityOnFireExtinguishedSound` plays GENERIC_EXTINGUISH_FIRE at volume 0.7 with
  pitch 1.6 + (`nextFloat()` - `nextFloat()`) * 0.4.
- The sound seed is already random in `compare.RANDOM_FIELDS`, but the pitch is not, so
  `player/fire` masks it.

## Live

- Healing between cases: `effect give <bot> minecraft:instant_health 1 5 true`. `kill` then
  `respawn` gives full air, health and food and no fire.
- A removed bed drops an item, which the Bot picks up (the ids shift): the Group kills items last.
- Control in view re-sends its entity data a tick after a respawn: it is put 96 blocks away.
  The Group does not turn `spawn_mobs` on or kill entities: the Fixture world has it off (ADR-0013)
  and its flat world generates no mobs. (The animals the first probes saw came from this Group's
  own `spawn_mobs true`, set when an earlier play ended.)
- Landing in water loses air in real time: the Bot lands with its head out, after a stop one tick
  above.
- A server saves a player where it leaves, so a Bot left in a pool or in stone rejoins inside
  that block on the next play: the Group puts each Bot back at the spawn when it ends.
- `player/fall`: the floating time of a 23 block fall (the teleport, then each move followed by a
  step and a barrier, about 30 to 35 ticks) stays under vanilla's 80 tick floating kick
  (`ServerGamePacketListenerImpl.tick`, `aboveGroundTickCount`). Under load the margin is about 2 s.
- Each hit window must open before the next hit (10 ticks for suffocation, the fire block, lava and
  the fall to dry grass; 20 for drowning and burns; 40 for freezing). The Group times the gap with
  a clock and fails when it is too long (`ProtocolError`), instead of comparing windows that
  hold another health.
- Fire: a player already burning in a fire block gets `nextInt(1, 3)` more fire ticks each tick
  (`BaseFireBlock.fireIgnite`), so the second hit there is `on_fire` instead of `in_fire` about 1
  play in 512 (2^-9). The Group takes the first hit in fire only.
- Fire: the move from lava onto dry grass must come within about 9 ticks of the last lava hit, so
  that the first burn hit is at 280 ticks of fire and not 300.
- 8 of 8 fall plays, 5 of 5 drowning, 6 of 6 suffocation, 5 of 5 void, 6 of 6 fire (with the pitch
  masked) and 6 of 6 freezing matched.
