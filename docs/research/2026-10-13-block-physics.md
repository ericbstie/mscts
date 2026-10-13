# How vanilla drops falling blocks and pops off blocks that lose their support — 2026-10-13

Evidence for #37 (`blocks/gravity`, `blocks/support`). Facts are **verified** with
`scripts/research/javap.py` on the 26.3 server jar unless a line says *live* (two vanilla 26.3
Instances, a draft of each Group played with `scripts/research/probe_loop.py`, 2026-10-13).

## A block that falls

- `FallingBlock.onPlace` and `FallingBlock.updateShape` schedule a tick of the block
  (`getDelayAfterPlace`, 2). `FallingBlock.tick` makes a `falling_block` entity if the block
  under it is free (`isFree`: air, fire, a liquid, or a block that can be replaced) and the block
  is not below the world. So a block placed by `/setblock` schedules a tick too, which does
  nothing while the block under it stands.
- `FallingBlockEntity.fall` puts the entity at the block's centre, x + 0.5 and z + 0.5, at the
  block's y, with no speed. It sets the block to air (`setBlockAndUpdate`), which updates the
  block above, which schedules its own tick.
- Each tick of the entity: `time` + 1, gravity 0.04 (`getDefaultGravity`), move, then speed x
  0.98 (`getAirDrag`).
- When it is on the ground, or a concrete powder whose block holds water, it lands where it is
  if that block can be replaced (`DirectionalPlaceContext`, facing down), it survives there, and
  the block under it is not free. Then it sets the block, sends the block (`block_update`) and an
  `add_transient_block` to every player that tracks it, is removed, and calls `Fallable.onLand`.
- Otherwise it is removed and, if it drops items and `entity_drops` is on, breaks into its item
  (`Entity.spawnAtLocation`). A torch or a bottom slab under it cannot be replaced, so sand that
  falls onto one breaks.
- `Entity.spawnAtLocation` puts the item where the falling block is, with no offset. The
  `ItemEntity` constructor draws its sideways speed (`nextDouble() * 0.2 - 0.1`) and its yaw
  (`nextFloat() * 360`).
- `AnvilBlock.onLand` plays world event 1031. `ConcretePowderBlock.onLand` turns the powder
  into concrete when it lands in water.

### An anvil that falls far is chipped at random

- `Entity.checkFallDamage` adds `-(double)(float)dy` to the fall distance each move, and on the
  ground calls `Block.fallOn`, which calls `causeFallDamage`.
- `AnvilBlock.falling` makes the entity hurt others (2 a block, at most 40).
  `FallingBlockEntity.causeFallDamage` then takes `i = ceil(fallDistance - 1)`. If the damage
  (`min(floor(i * 2), 40)`) is above 0, an anvil draws `random.nextFloat() < 0.05 + 0.05 * i`
  from the entity's own random, and if it is true the anvil lands one stage more damaged.
- So an anvil that falls 10 blocks lands chipped half the time, and no Group can compare it tick
  by tick. One that falls 1 block has a fall distance of 0.99999998 (the float casts, worked out
  in `fall_sim.py` in the probe's scratch dir): `i` is 0, nothing is drawn.

### When (*live*)

- The block above the removed one becomes a `falling_block` on the second step after the
  window's `setblock ... air` (the delay of 2): `add_entity`, its start position in
  `set_entity_data` (twice), the block set to air, and a `move_entity_pos` of 0. The block above
  that falls two steps later, and so on up a column.
- After a fall of one block it lands on the 8th step: `block_update`, `add_transient_block`,
  `remove_entities` and `block_update` again. The anvil's world event 1031 comes before the
  second `block_update`. The column of 6 lands its last block on the 18th step.
- Concrete powder that falls one block into water lands on the 8th step. The first `block_update`
  is the powder and the second is the concrete.
- Sand that falls 2 blocks onto a torch breaks on the 11th step, and 1.5 blocks onto a bottom
  slab on the 10th: `remove_entities`, then the item's `add_entity` at the falling block's place
  (x 11.5, y -60.0) and its stack in `set_entity_data`.
- A window that ended a step before the sand broke missed the item, which then moved at random in
  the next window: 6 plays of 6 did not match. Ended on the step it breaks, 20 plays of 20 match.
- While it falls, the entity sends `set_entity_motion` and `move_entity_pos` every third step.
- A step took about 300 ms on each side.
- A packet comes in step k when it arrives between the Marks `tick:<k-1>` and `tick:<k>` (the
  barrier at the end of each step); the first count of these steps read them one step early.

## A block that loses its support

- `/setblock` without `strict` places with flags 2 and 256 (`UPDATE_CLIENTS`,
  `UPDATE_SKIP_BLOCK_ENTITY_SIDEEFFECTS`), so the neighbours' shapes are updated, and then calls
  `updateNeighboursOnBlockSet`. `strict` uses 816, which also skips `onPlace`, drops and shape
  updates.
- `BlockInput.place` fits the block to its neighbours (`Block.updateFromNeighbourShapes`) but
  keeps the given state if that would make it air, so one half of a door or a bed can be set
  alone.
- A torch, a lever, a flower, a door, a wall torch and a ladder check their support in
  `updateShape`; a block that no longer survives becomes air through `Block.updateOrDestroy`,
  which breaks it with its drops (`destroyBlock`). A rail checks in `neighborChanged`
  (`BaseRailBlock`): it drops its item and is removed without break particles.
- A bed needs nothing under it: `AbstractBedBlock` has no `canSurvive`, and its `updateShape`
  looks only at its other half.

### When (*live*)

- Every block pops off inside the command that removes its support, before the first step:
  break particles (world event 2001, but not for the rail), the item (`add_entity`, a random
  place and speed, the stack in `set_entity_data`), and a `section_blocks_update` of both
  cells. The door sends world event 2001 for both halves and drops one item. The bed stays.
- Nothing came in the step after.
- An item left on the ground sends `set_entity_motion` and `move_entity_pos` in later steps, at
  random, so each window's item is killed before the next window.
- 20 plays of 20 matched, with a draft that killed no items.
