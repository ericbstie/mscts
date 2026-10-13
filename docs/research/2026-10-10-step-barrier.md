# A Bot's action before a step — 2026-10-10

Evidence for #360: in a window where a Bot acts and the world then steps, the Bot's
action travels on its own connection and Control's `tick step 1` on another. Facts are
**verified** with `scripts/research/javap.py` on the 26.3 server jar, unless a line says
*live*.

## The queues the action and the barrier cross

- Every packet of a Bot's action calls `PacketUtils.ensureRunningOnSameThread` first:
  `handlePlayerAction` (dig, drop), `handleAttack`, `handleInteract`, `handleUseItemOn`
  (place), `handleMovePlayer` (move), `handlePunch` (the swing), `handlePlayerInput`,
  `handlePlayerCommand`, `handleSetCarriedItem`, `handleClientTickEnd` and
  `handleContainerClick`. So does `handleClientCommand`, the barrier's request.
- Off the main thread, `ensureRunningOnSameThread` hands the packet to
  `PacketProcessor.scheduleIfPossible`. That adds it to `packetsToBeHandled`, a single
  `ConcurrentLinkedQueue` for the whole server (FIFO). One connection's packets enter it
  in the order they came.
- `MinecraftServer.processPacketsAndTick` calls `processQueuedPackets`, which handles
  packets until the queue is empty, then calls `tickServer`. Nothing there checks the
  freeze: a frozen world still handles every packet once per tick
  (docs/research/2026-10-03-tick-step.md).
- `handleClientCommand` answers `REQUEST_STATS` with `award_stats` in the handler
  (docs/research/2026-09-30-observation-window.md).
- `handleChatCommand` does not call `ensureRunningOnSameThread`. The command runs as a
  server task, between ticks (`tryHandleChat` → `server.execute`,
  docs/research/2026-10-01-control.md).

So once the Bot has the answer to a request it sent after its action, the server has
handled the action. Control sends `tick step 1` after that answer, so the step reaches the
server after the action was handled, and before the tick it steps.

Without the barrier, a server that runs Control's command before it handles the Bot's
packet, or a host that delays that packet past a tick, moves the action to the next tick.

## Live

- *Live*, 20 plays on each of two vanilla Instances: `blocks/dig-creative`'s four digs,
  with `digger.sync()` between the dig and `context.step(1)`, in a frozen world. All 20
  plays matched. For all 160 digs, the digger received its `block_changed_ack` (and, for
  the three that break the block, its `block_update`) before Control sent `tick step 1`.
  Both came about 50 ms after the dig, and the step went out about 100 ms later.

`GroupContext.step_after` is that barrier, then the step.

## A lighter proof: two requests, back to back — 2026-10-13

The full barrier (`Bot.sync`, three requests a pass apart) also proves that the server has
sent everything the action caused. A step does not need that before it: the step's own
barrier covers it afterwards. With it, `player/fall` (58 steps a play) took about 89 s a
play, both sides, under stress, against the Self-check's 90 s. So `step_after` now calls
`Bot.wait_until_handled`: `HANDLED_REQUESTS` (2) requests sent back to back, then as many
`award_stats`.

- `ServerStatsCounter.sendStats(ServerPlayer)` is the only place the 26.3 server builds a
  `ClientboundAwardStatsPacket` (bytecode 60–68: the dirty statistics, then
  `connection.send`). Of the server's classes, only `ServerStatsCounter`, the packet
  itself, `ClientGamePacketListener`, `GamePacketTypes` and `GameProtocols` name the
  packet, and only `ServerGamePacketListenerImpl` calls `sendStats`: in
  `handleClientCommand`, for `REQUEST_STATS` (bytecode 194–205), after
  `ensureRunningOnSameThread` (bytecode 9). So vanilla sends `award_stats` only as the
  answer to a request, in its handler.
- So for vanilla one request would do. The javap says nothing about a Candidate, which may
  send `award_stats` unasked (#169). Taken as the answer, one such stray would end a
  one-request proof before the server had handled the action. With two requests, one stray
  still leaves a real answer among the two `award_stats` taken, and that answer came after
  the action. Two strays during one proof can still end it early, as with `sync`.
- Sent back to back, both requests reach the same packet pass, so the second costs about
  nothing. *Live*, one vanilla Instance, frozen, 100 rounds of a swing then
  `wait_until_handled`, and a swing then `sync`, with two busy loops beside it:
  `wait_until_handled` took 49.8 ms (median; 56.6 ms at most), and its two answers came
  0.00 ms apart (median; 3.12 ms at most, never over 5 ms: one pass); `sync` took 149.2 ms
  (median). The Bot sent 500 requests and took 500 `award_stats`, none passed over: vanilla
  sent none unasked.
