# Which jumps vanilla counts, and the player ticks between them — 2026-10-17

Evidence for #354: in a draft `player/exhaustion` with 50 walking jumps, the two vanilla
Instances sometimes read back exhaustion 0.05 apart, one jump. Facts are **verified** with
`scripts/research/javap.py` on the 26.3 server jar unless a line says *live*.

## When vanilla counts a jump

- `ServerGamePacketListenerImpl.handlePlayerPositionChange` (offsets 446 to 511) takes
  `dy` as the packet's y minus `lastGoodY`, and calls `ServerPlayer.jumpFromGround` (the
  jump's exhaustion, 0.05 walking, and the `jump` statistic) when `player.onGround()` is true,
  the packet's `onGround` is false and `dy` is above 0. It reads `onGround()` before it moves
  the player.
- After the move, the same method sets the player's `onGround` from the packet's flag
  (`setOnGroundWithMovement`, offset 1026). So each move leaves `onGround` as the client said.

## What a player tick does to it between two moves

- `ServerGamePacketListenerImpl.tick` calls `tickPlayer` every server tick, frozen or not
  (only a paused server skips it). `tickPlayer` saves the position (`resetPosition`), calls
  `ServerPlayer.doTick`, then puts the player back where it was (`absSnapTo`, offsets 53 to 83).
  It does not put `onGround` back.
- `doTick` runs `Player.tick`, and so `LivingEntity.aiStep`, which calls `travel` when
  `canSimulateMovement()` and `isEffectiveAi()` hold. On the server both hold for a player:
  `Player.getMoveSimulationType` is `AUTHORITATIVE_SIDE_AND_SERVER`. So the server moves the
  player by its own velocity each player tick, with gravity (0.08) and drag (0.98) after the
  move, and `aiStep` zeroes a vertical speed under 0.003.
- `Entity.move` (offsets 441 to 530) sets `onGround` from that move's collision whenever the
  move's `dy` is not 0: a move up leaves the ground and sets it false, a move down into the
  ground sets it true and stops the fall.
- `jumpFromGround` gives the player a vertical speed of 0.42 (`LivingEntity.jumpFromGround`).
  Tick by tick it is 0.42, 0.3332, 0.2481, 0.1648, 0.0831, 0.0030, then -0.0754. So for 6
  player ticks after a jump the server's own move goes up. A player tick at the ground in that
  time sets `onGround` false, and a jump the client sends then is not counted. From the 7th tick
  on, a tick at the ground sets it true again.
- `ServerPlayer.doTick` raises the `play_time` statistic every player tick (offsets 49 to 60).
  In the 26.3 data generator's registries, the stat type `minecraft:custom` is 8, and its
  `minecraft:play_time` is 1 and `minecraft:jump` is 23. So the `award_stats` that answers each
  barrier says how many player ticks have run and how many jumps were counted.

## Live

`scripts/research/exhaustion_jumps.py` plays the jump part alone on two fresh vanilla
Instances: a jump tick, a move up to y -59.58 (not on the ground), barriers, a move down to
y -60 (on the ground), a barrier.

- *Live*, 1 play, no load, with one barrier in the air as in the draft: each side counted 25 of
  the 50 jumps, every other one. Each jump took 6 player ticks (49 of 49 on one side). Every
  jump 5 or 6 ticks after the last counted one was missed (50 of 50), and every one 11 or 12
  ticks after was counted (48 of 48). The play matched only because both sides took 6 ticks a
  jump. A side that takes 7 for some jumps counts more of them.
