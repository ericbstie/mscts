# A player's saturation grows while it is online in peaceful — 2026-10-03

Evidence behind `join/basic` (#30) turning off `natural_health_regeneration`.

Facts are **verified** with `scripts/research/javap.py` on the 26.3 server jar
unless a line says *inferred*.

## What was measured

The first Self-check of `join/basic` (`MSCTS_SELFCHECK_REPEAT=20`, the default
ServerSpec, which is peaceful) matched in 1 play of 20. Every other play differed
only in `set_health.saturation`: 6.0 on one Instance, 5.0 on the other. After the
run, `alice`'s saved player data held `foodSaturationLevel` 6.0 on the first
Instance and 5.0 on the second. A new player starts at 5.0.

## Why

- `ServerPlayer.tickRegeneration`: when the level's difficulty is `PEACEFUL` and
  the game rule `NATURAL_HEALTH_REGENERATION` is on, then every 20 of the
  player's ticks (`tickCount % 20 == 0`) the player heals 1 if hurt, and its
  saturation goes up by 1 while it is below 20. Every 10 ticks its food level goes
  up by 1 if it needs food.
- The rule is `natural_health_regeneration` (`GameRules`, a boolean, `true` by
  default).
- The player's saturation is saved with it, and the next join sends it in
  `set_health`. So how many times a play's player reached a 20th tick before it
  left changes what the next play's join sends. That depends on timing: *inferred*,
  from one Instance having gone up once (the first, slower play, presumably) and
  the other not at all.

## What the Group does

With `gamerule natural_health_regeneration false`, nothing in
`tickRegeneration` runs. A player whose health and food are full, standing still,
then keeps the saturation it joined with. `join/basic` sets the rule before its
player joins and puts it back afterwards.
