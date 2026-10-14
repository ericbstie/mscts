# When vanilla breaks a block a survival player finished early — 2026-10-14

Evidence for #347 (`blocks/dig-survival`, split from #36). Facts are **verified** with
`scripts/research/javap.py` on the 26.3 server jar unless a line says *live*
(`scripts/research/dig_finish.py`, one vanilla 26.3 Instance, 2026-10-14).

PR #343 saw an early finish accepted from a digger that had been in the world for about 8 s and
refused from one that had just respawned. Three causes were open: (a) a STOP judged against an
older START, (b) the delayed destroy a refused STOP arms, (c) the 60-tick `hasClientLoaded` gate.
It is (b): the delayed destroy counts its progress from when the player was made, not from the
START.

## The rule

- `ServerPlayerGameMode.tick` adds 1 to `gameTicks` on every call (bytecode 0-7), and
  `ServerPlayer.tick` calls it every tick (0-11), frozen world or not. A respawn makes a new
  `ServerPlayer` (`PlayerList.respawn`), whose constructor makes a new `ServerPlayerGameMode`
  (`ServerPlayer.<init>` 252-255). `restoreFrom` copies only the game mode (16-34), so
  `gameTicks` starts again at 0 at every join and respawn.
- START (`handleBlockBreakAction` 274-279) sets `destroyProgressStart = gameTicks`, with no
  condition once the range, spawn protection, `mayInteract`, creative and
  `blockActionRestricted` checks pass.
- STOP (547-641) breaks the block when it is still at `destroyPos`, not air, and
  `getDestroyProgress * (gameTicks - destroyProgressStart + 1) >= 0.7`.
- Otherwise, if no delayed destroy is armed (642-669), it arms one: `isDestroyingBlock = false`,
  `hasDelayedDestroy = true`, `delayedDestroyPos = pos`, `delayedTickStart =
  destroyProgressStart`. If one is armed already, the STOP does nothing more.
- Each later tick (`tick` 10-78), with a delayed destroy armed: air at its cell disarms it.
  Otherwise it calls `incrementDestroyProgress(state, pos, delayedTickStart)` and breaks the
  block (`destroyBlock`) when that is 1 or more. The `isDestroyingBlock` branch is an `else`,
  so it does not run while a delayed destroy is armed.
- `incrementDestroyProgress(state, pos, n)` (0-21) returns `getDestroyProgress * (n + 1)`. It
  does not subtract `gameTicks`. The `isDestroyingBlock` branch passes the ticks since the START
  (139-148, 172); the delayed branch passes `delayedTickStart`, the player's own tick count at
  the START.

So a STOP the 0.7 check refuses breaks the block on the player's next tick if
`progress * (ticks alive at the START + 1) >= 1`, and never if not, since `delayedTickStart`
does not change. Stone by hand (1/150 a tick) breaks so from a player alive 149 ticks (about
7.5 s); obsidian with a diamond pickaxe (8/50/30 a tick) from one alive 187 ticks (about 9.4 s).

## What the watcher is told

- `incrementDestroyProgress` sends the crack stage `(int)(progress * 10)` to every other player
  within 32 blocks when it differs from the last one sent (22-60, `ServerLevel.destroyBlockProgress`
  48-138). A START sends stage `(int)(progress * 10)` of one tick, 0 for these blocks
  (469-508). An accepted STOP sends -1 (623-628), 255 as the unsigned byte on the network.
- So a delayed destroy tells the watcher a stage of 10 or more before the block breaks, and a
  refused one a stage under 10 that then never changes.

## The load gate is not it

- `ServerGamePacketListenerImpl.handlePlayerAction` returns before anything else while
  `hasClientLoaded()` is false (12-19), and the `block_changed_ack` is sent only after
  `handleBlockBreakAction` (302-307). So a STOP the gate drops gets no acknowledgement.
- `hasClientLoaded` is `!waitingForRespawn && clientLoadedTimeoutTimer <= 0`
  (`CLIENT_LOADED_TIMEOUT_TIME` 60). `player_loaded` clears the timer; `Bot.join` and
  `Bot.respawn` send it after the first chunk batch.

## The probe (*live*)

The digger stands at (8.5, -60, 4.5) in a frozen world and sends a START and a STOP one client
tick apart, each case at a cell no START had named before, which rules out (a). It waits, reads
everything, then sets air at the cell and steps a tick. The age is from the digger's `respawn`
(or `login`) to its START, as the Transcript recorded them.

| Case | Age (s) | Acknowledged | Broke | Watcher's stages |
| --- | --- | --- | --- | --- |
| stone by hand, just respawned, watched 10 s | 0.58 | yes | no | 0 |
| stone by hand, same life | 11.77 | yes | 99.7 ms after the STOP | 0, 15 |
| stone by hand, respawned | 4.02 | yes | no | 0, 5 |
| stone by hand, same life | 6.70 | yes | no | 0, 9 |
| stone by hand, same life | 9.02 | yes | 82.5 ms after the STOP | 0, 12 |
| obsidian, diamond pickaxe, respawned | 5.01 | yes | no | 0, 5 |
| obsidian, diamond pickaxe, same life | 12.01 | yes | 85.7 ms after the STOP | 0, 12 |

Every STOP was acknowledged, which rules out (c). Every second stage is
`(int)(progress * (ticks alive + 1) * 10)` at 20 ticks a second (stone at 4.02 s: 81 ticks,
0.54, stage 5), and the block broke exactly when it reached 10. The finish 0.58 s after the
respawn was never broken, though the digger lived another 10 s.

## For a Group

- An early finish from a player alive less than `1 / progress - 1` ticks is refused for good;
  air at the cell disarms the delayed destroy on the player's next tick.
- An early finish from a player alive longer breaks the block a tick or two later, with no
  check of how long the dig took. A Candidate that refuses it differs from vanilla.
- The count is the player's own ticks, which run on the clock in a frozen world, so a Group
  cannot step them: it times the digger's age and the dig by the clock.
