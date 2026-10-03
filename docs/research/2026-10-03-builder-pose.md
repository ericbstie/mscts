# Why the builder sometimes crawled — 2026-10-03

Evidence behind #170. In the Self-check, `blocks/clone` sometimes did not match:
one vanilla Instance sent the `builder` Bot a `set_entity_data` with its pose
(index 6) set to 3 or 0, or its health (index 9) set to 19.0, and the other
Instance did not.

Facts are **verified** with `scripts/research/javap.py` on the 26.3 server jar
unless a line says *inferred*.

## Where a player joins

- `PlayerSpawnFinder.findSpawn` reads `GameRules.RESPAWN_RADIUS`, caps it by the
  distance to the world border, and searches from a random start
  (`RandomSource.createThreadLocalInstance().nextInt(...)`). In adventure mode
  it uses the spawn itself.
- `GameRules` registers `respawn_radius` with the default 10.
- A fresh flat world's spawn is (0, -60, 0) (`2026-09-26-pumpkin.md`). A
  player's join place is random once per world: the server saves it with the
  player (`2026-10-01-join-chunks.md`). So the builder stands somewhere with x
  and z from about -10 to 10, and the two Instances of a Self-check each pick
  their own place.

## What a block in the player's space does

- `Pose` (`<clinit>`): `STANDING` is 0, `FALL_FLYING` 1, `SLEEPING` 2,
  `SWIMMING` 3. Pose 3 is the crawling pose.
- `Player.updatePlayerPose`: when the pose the player wants does not fit
  (`canPlayerFitWithinBlocksAndEntitiesWhen`), it takes `CROUCHING` if that
  fits, else `SWIMMING`, then `setPose`. When the blocks go again, the pose goes
  back to `STANDING` (0).
- `LivingEntity.baseTick`: when `isInWall()`, it calls
  `hurtServer(level, damageSources().inWall(), 1.0F)`. A player at 20 health
  drops to 19.
- *Inferred*: each change is sent as a `set_entity_data` to the player itself,
  on the player's next tick. Whether that tick falls inside the Observation
  window depends on timing, which is why the mismatch did not come every play.

## Which blocks were in the way

The Groups set blocks at y -60 to -58, the height of a standing player on the
flat world (feet at -60, head below -58.2):

- `blocks/setblock`: x 1 to 14 at z 2.
- `blocks/clone`: x 2 to 10, z 8 to 11.

Both are inside the area the builder can join in. `blocks/fill` sets blocks at y
-50 to -46, above any player on the ground.

## The fix

Control moves the builder with `tp builder 0.5 -60 14.5` before the first
window. A standing player is 0.6 wide and 1.8 high, so it then fills x 0.2 to
0.8 and z 14.2 to 14.8, clear of every block the Groups set, and it is still in
chunk (0, 0).
