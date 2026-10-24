# What droppers and dispensers do on a pulse, and when — 2026-10-24

Evidence for #490, `redstone/dropper-dispenser`. Facts are **verified** with
`scripts/research/javap.py` on the 26.3 server jar unless a line says *live*. Quasi-connectivity
and the click of an empty one are in docs/research/2026-10-22-pistons.md.

## When a pulse triggers them

- `DispenserBlock.neighborChanged` (the dropper inherits it): powered is
  `hasNeighborSignal(pos) || hasNeighborSignal(pos.above())`. Powered and not `triggered`, it
  schedules its own block tick 4 ticks on (`scheduleTick(pos, this, 4)`) and sets
  `triggered=true` with flags 2. Not powered and `triggered`, it sets `triggered=false`. Any
  other neighbour change does nothing, so a dispenser that stays powered acts once.
- `DispenserBlock.tick` calls `dispenseFrom` and checks no power. A pulse that ends before the
  tick still dispenses, 4 ticks after it began.
- So a redstone block that Control sets beside one between steps, after k steps, makes it act on
  the step of tick k + 4. Block ticks run in a tick before the entities and the block entities
  (`ServerLevel.tick`), and a frozen world runs them only on the ticks it steps.

## Which slot

- `DispenserBlockEntity.getRandomSlot` walks the 9 slots in order and keeps the n-th non-empty
  slot if `random.nextInt(n)` is 0, n counting from 1: a uniform pick among the non-empty
  slots. With one non-empty slot it is always that slot (`nextInt(1)` is 0), whichever slot it
  is. With none it answers -1.
- `DispenserBlock.dispenseFrom` and `DropperBlock.dispenseFrom`: on -1, world event 1001 (the
  click) and nothing else.

## A dropper into a container

- `DropperBlock.dispenseFrom` looks for a container in front (`HopperBlockEntity.getContainerAt`).
  If there is one, it adds one item of the picked slot's stack (`HopperBlockEntity.addItem`,
  which tries a chest's slots in index order) and takes it from the stack if it went in.
  It plays no world event and no sound. A container with no room takes nothing, and the
  dropper keeps its item and tries no more until its next pulse.
- With no container in front, a dropper drops the item as a dispenser drops an item it has no
  behaviour for (`DefaultDispenseItemBehavior`).

## What a dispenser does with an item

- `DispenserBlock.getDispenseMethod` takes the item's registered behaviour. An item with none
  that has an `equippable` component gets `EquipmentDispenseItemBehavior`; any other gets
  `DefaultDispenseItemBehavior`, which drops it as an item entity with a random motion
  (`spawnItem`).
- `DefaultDispenseItemBehavior.dispense` runs the behaviour, then world event 1000 at the
  dispenser (data 0) and world event 2000 at the dispenser, its data the facing's 3D value
  (east is 5). Every behaviour below goes through it, unless it says otherwise.
- `consumeWithRemainder` takes one item from the stack. If that empties the stack, the remainder
  (an empty bucket) takes its place in the same slot.

### A water bucket, and an empty one

- `DispenseItemBehavior$3` (the water bucket and the other filled buckets) calls
  `BucketItem.emptyContents` on the block in front. If it places the water, the stack becomes
  an empty bucket (`consumeWithRemainder`); if not, the bucket is dropped as an item.
- `BucketItem.emptyContents`, into air: `setBlock(pos, water, 11)`, then `playEmptySound`:
  `BUCKET_EMPTY` at the block, category blocks, volume 1 and pitch 1, both fixed. Only a
  dimension where water evaporates plays a sound with a random pitch.
- `LiquidBlock.onPlace` schedules the water's fluid tick 5 ticks on. A source with solid blocks
  on every side but the dispenser's flows nowhere when it ticks.
- `DispenseItemBehavior$4` (the empty bucket) picks up the fluid in front
  (`BucketPickup.pickupBlock`; `LiquidBlock.pickupBlock` sets air with flags 11 and plays no
  sound), and the stack becomes a water bucket. With nothing to pick up, it drops the bucket.

### Armor

- `EquipmentDispenseItemBehavior.dispenseEquipment` takes the living entities in the block in
  front that `canEquipWithDispenser`: alive, the item's `equippable` dispensable and for a slot
  the entity uses, and that slot empty. It puts one item in that slot of the first one
  (`setItemSlot`). With none, it drops the item.
- `LivingEntity.onEquipItem` plays the item's equip sound at the entity with
  `playSeededSound`, volume 1 and pitch 1, both fixed. It plays nothing while the entity has not
  ticked yet (`firstTick`).
- `LivingEntity.tick` sends the change (`detectEquipmentUpdates`, then
  `ClientboundSetEquipmentPacket` to the players tracking it), in the entity's own tick. Entities
  tick after block ticks, so `set_equipment` leaves in the tick the dispenser acts.
- An armor stand that `/kill` removes is gone at once and drops nothing. `/kill` hurts it with
  generic kill (`LivingEntity.kill`), which bypasses invulnerability, so `ArmorStand.hurtServer`
  calls `kill(level, entity)`, which only removes it (`remove(KILLED)`).

### An arrow

- `ProjectileDispenseBehavior.execute` makes the arrow at a fixed place, 0.7 past the
  dispenser's centre along its facing and 0.1 up (`ProjectileItem.DispenseConfig`), then shoots
  it with `Projectile.spawnProjectileUsingShoot`, power 1.1 and uncertainty 6 (the defaults,
  which `ArrowItem` keeps). It plays world event 1002, not 1000.
- `Projectile.getMovementToShoot` adds `random.triangle(0, 0.0172275 * 6)` to each axis of the
  facing, from the arrow's own random source. `Projectile.shoot` sets the yaw and the pitch from
  that motion (`Mth.atan2`).
- The arrow is shot before `addFreshEntity`, so its `add_entity` carries that random motion on
  all three axes, and the yaw and the pitch made from it
  (`ClientboundAddEntityPacket(Entity, ServerEntity, int)` takes the `ServerEntity`'s last sent
  rotation and motion). Its place is fixed.
- No Mask in the Groups today hides an `add_entity`'s pitch: `blocks.DROP_MASKS` hides the
  place, the x and z motion and the yaw, and `inventory.DROP_MASKS` the motion and the yaw. So
  comparing a fired arrow's `add_entity` takes a new Mask.
