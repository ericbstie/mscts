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
