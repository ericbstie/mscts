# How vanilla checks the moves a player reports — 2026-10-04

Evidence for #60, the movement Groups. Facts are **verified** with
`scripts/research/javap.py` on the 26.3 server jar
(`ServerGamePacketListenerImpl`, `ServerPlayer`, `Entity`, `Direction`) unless a line says
*live* (observed on a vanilla 26.3 Instance) or *inferred*.

## A move packet, in order

- `handleMovePlayer` first checks `containsInvalidValues(x, y, z, yRot, xRot)` and kicks
  with `multiplayer.disconnect.invalid_player_movement` if it is true. It is true for a NaN
  coordinate (`Double.isNaN`) or a rotation that is not finite (`Floats.isFinite`). An
  infinite coordinate is not invalid: it is clamped, to ±3·10⁷ across and ±2·10⁷ up.
- A second move with a position in one client tick is a kick, with the same message
  (`receivedPositionThisTick`). `handleClientTickEnd` resets it, and every `Bot.move` sends
  `client_tick_end` after its move.
- While the server waits for the client to accept a teleport (`updateAwaitingTeleport`), a
  move only sets the rotation. The teleport is sent again after 20 ticks without an accept.
- `handleAcceptTeleportPacket` calls `handlePlayerPositionChange` with the accepted pose,
  so the accept counts as a move, for the speed check and the floating flag alike.

## The speed check

- `handlePlayerPositionChange` measures the move from `firstGoodX/Y/Z`, where the player
  was when the tick began (`tickPlayer` calls `resetPosition` every tick).
- It counts the move packets since the tick began (`receivedMovePacketCount` less
  `knownMovePacketCount`, which `tickPlayer` sets). Past 5, the count is set back to 1.
- The move is refused, and the player sent back, when `dist² − velocity² > 100 · n`
  (300 while gliding), n being that count.
- The whole branch runs only when `TickRateManager.runsNormally()` is true, so never in a
  frozen world, and the count goes up only there. `shouldCheckPlayerMovement` then turns it
  off when the game rule `player_movement_check` is false (and while gliding, when
  `elytra_movement_check` is false).
- The game rule gates only this branch: the collision, awaiting-teleport and floating
  checks run with it off.
- `ServerPlayer.teleport` calls `connection.teleport` and then `resetPosition`, so the
  accept of a `/tp` is measured from the new place.
- After a stepped tick (`tick step`), `runsNormally()` stays true for the next packet pass:
  `processPacketsAndTick` drains the packets before `tickServer`, whose
  `TickRateManager.tick()` sets it again (docs/research/2026-10-03-tick-step.md). So a
  long move that lands in that pass is checked for speed in a frozen world.
- *Live*: moves of 1, 5 and 9 blocks pass; 11 and 20 are sent back to the start. Two moves
  of 8 in one tick: the second is sent back to the first. Six moves of 2 in one tick: the
  sixth is sent back to the fifth, x 18.5. Each correction is absolute (flags 0); a `/tp`'s
  `player_position` has flags 24.

## Collision and step-up

- The server moves its player by the reported change (`player.move`). If the player then
  ends more than 0.25 blocks from the reported place (`dist² > 0.0625`, a vertical
  difference within ±0.5 ignored), it "moved wrongly".
- It is sent back if it moved wrongly from a box that was clear, or if its new box collides
  with something it did not collide with before (`isEntityCollidingWithAnythingNew`).
- `Entity.collide` lets the move step up by `maxUpStep` when the player is on the ground.
  `collideWithShapes` takes the axes in `Direction.axisStepOrder`: Y first, then X and Z
  (Z before X when |x| < |z|). So a move up and across onto a block or slab, without a jump,
  is not refused.
- None of this is gated by `runsNormally()`.
- Into a wall 0.5 blocks off: `player.move` stops at x 4.7, 0.8 short, which is moved
  wrongly from a clear box, so the player goes back to x 4.5. A 0.6-wide, 1.8-high player
  fits a gap 1 wide and 2 high. (Review B of #277, from the bytecode; the Self-check of
  `movement/into-blocks` matched 20 of 20.)

## Floating

- An accepted move sets `clientIsFloating` when it rises by at least −1/32, the player did
  not collide below before the move (`verticalCollisionBelow` is read before it), and the
  player is not a spectator, may not fly (`allowFlight`, `mayfly`), has no levitation, is
  not gliding or spinning, and has no block around it.
- `tickPlayer` counts `aboveGroundTickCount` up while the player floats and kicks with
  `multiplayer.disconnect.flying` once it passes `getMaximumFlyingTicks`:
  `ceil(80 · max(0.08 / gravity, 1))`, 80 for a player.
- `tickPlayer` runs from `tickConnection`, which `tickChildren` calls without checking
  `runsNormally()`, so a frozen world counts the same.
- *Live*: a survival Bot that hovers 1.5 blocks up is kicked about 4.05 s after its second
  move in the air.
- *Live*: after a `movement/flying` play, the kicked Bot and the creative one (back in
  survival) rejoin at y −58.4, where the play left them, and are kicked for flying when left
  idle. The join's accept sets `clientIsFloating`, so a Bot that rejoins in the air is kicked
  80 ticks later unless it is moved.
