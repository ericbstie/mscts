# How often vanilla hurts a drowning player, and what a Bot sees between two hits — 2026-10-22

Evidence for #345. Facts are **verified** with `scripts/research/javap.py` on the 26.3 server jar
unless a line says *live* (two vanilla 26.3 Instances, 20 plays, 2026-10-22).

## Air

- `LivingEntity.baseTick`: with the eyes in water and no bubble column at the eyes, a player
  drowns unless `canBreatheUnderwater`, it has water breathing (`MobEffectUtil.hasWaterBreathing`),
  or its abilities make it invulnerable (creative). A drowning player's air is set to
  `decreaseAirSupply(air)`, and when it is -20 or less (`shouldTakeDrowningDamage`), it is set to
  0, entity event 67 (the bubbles) is broadcast and the player is hurt for 2 by `drown`.
- `decreaseAirSupply` is `air - 1`, unless the `OXYGEN_BONUS` attribute is above 0 and
  `random.nextDouble() >= 1 / (bonus + 1)`: then the air stays. A Bot has no such bonus, so its
  air goes down exactly 1 a tick, and the hits come every 20 of its ticks.
- A player in water that does not drown gets air back only when `shouldEffectsRefillAirsupply`
  says so. Out of water the air goes up 4 a tick (`increaseAirSupply`) to the most it can have.
- `TickRateManager.isEntityFrozen` is false for any `Player`: `tick freeze` and `tick step` do not
  stop or step a player's ticks, so its air runs on the wall clock.
- `ServerPlayer.doTick` runs `Player.tick` (and with it `baseTick`) first, and sends `set_health`
  at its end when the health, the food or whether saturation is 0 changed.

## What the Bot sees (*live*)

- `effect give <bot> minecraft:instant_damage 1 1 true` takes 12 of a fresh Bot's health: 8 is left.
- Under water, the Bot gets one `set_entity_data` a tick that holds only the air (index 1, a
  VarInt), from 299 down to -19. Nothing else in its entity data changes.
- With `drowning_damage` off, the air running out sends `entity_event` 67, then a `set_entity_data`
  with the air at 0, and no damage.
- `gamerule drowning_damage true` sends the drowning Bot nothing.
- A hit sends `entity_event` 67, `damage_event`, `set_health`, then one `set_entity_data` with the
  air at 0 and the health (index 9). The air then goes -1 to -19, and the next hit comes.
- The killing hit sends `entity_event` 67, `damage_event` and `player_combat_kill`, then the death
  message; there is no `set_health` before the death.
- `set_time` comes every 20 ticks, between two air values, at a phase against the hits that
  differs between plays and Instances: it is no clock for the hits.
- In 20 plays, all 40 sides showed the same sequence: the bubbles without a hit, air 0 to -19,
  three hits each followed by air -1 to -19, and the killing hit. 20 of 20 plays matched.
