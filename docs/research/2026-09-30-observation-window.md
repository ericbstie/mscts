# Observation window: the barrier and heartbeat packets — 2026-09-30

Evidence behind #18: what a Bot does when an observation window ends, so
that it has everything the server sent because of what happened inside
the window, and which packets the server sends on a clock whatever a
Group does.

All facts are **verified** in this container, against vanilla 26.3 (the
Reference) and Pumpkin nightly sha256 `b8382a8a…` (installed with
`mscts adapter install pumpkin --from`; no Registry entry). Bytecode was
read with `scripts/research/javap.py` from the Reference jar. Live runs
used a research probe (`barrier.py` in the session scratchpad; not
committed) with the default ServerSpec (flat, seed 0, peaceful, view
distance 2), two Bots (`mscts_op`, an operator, and `watcher`), and chat
commands sent as the operator.

## When vanilla handles a packet — javap

- `PacketUtils.ensureRunningOnSameThread` hands a packet that needs the
  main thread to `PacketProcessor.scheduleIfPossible`, a FIFO queue, and
  aborts the handler on the network thread.
- `PacketProcessor.processQueuedPackets` empties that queue. Its only
  caller is `MinecraftServer.processPacketsAndTick`, **before**
  `tickServer`. So queued packets are handled once per tick, at its
  start, in arrival order.
- The main loop (`runServer`) is `processPacketsAndTick`, then
  `waitUntilNextTick`, which runs the task queue (`runAllTasks`,
  `managedBlock`). A chat command goes to that task queue
  (`handleChatCommand` → `tryHandleChat` → `server.execute`), so it runs
  **between** ticks. `shouldRun(TickTask)` is `task.tick + 3 < tickCount
  || haveTime()`: a command waits past the next tick only when the server
  has no time left in the tick (overloaded).
- `tickChildren` first calls `suspendFlushing()` on every player's
  connection, and last ("send chunks") calls `sendNextChunks` and
  `resumeFlushing()`. `ServerCommonPacketListenerImpl.send` flushes at
  once unless flushing is suspended and the caller is the main thread. So
  what a tick sends (block changes, entity changes) leaves the server at
  the end of that tick, together.
- `handleClientCommand` calls `ensureRunningOnSameThread`; action
  `REQUEST_STATS` (1) answers at once with `award_stats`
  (`ServerStatsCounter.sendStats`). So its answer is sent at the start of
  the next tick, before that tick's work, and flushed at once.
- `handlePingRequest` (play) sends `pong_response` directly, without
  `ensureRunningOnSameThread`: it is answered on the network thread, at
  any time.
- Packet ids (26.3): serverbound play `chat_command` 7, `client_command`
  12, `ping_request` 38; clientbound play `award_stats` 3, `block_update`
  8, `keep_alive` 45, `pong_response` 63, `set_time` 115, `system_chat`
  124.

## The barrier — live

The world frozen (`tick freeze`), the operator runs `setblock`, and then
each Bot at once runs one barrier variant. The effects are `system_chat`
and `block_update` for the operator and `block_update` for the watcher.
30 trials of each variant per server.

| Barrier | Vanilla: effects before its last answer | Pumpkin: effects before its last answer |
|---|---|---|
| one `ping_request` → `pong_response` | 0/30 (the pong comes first) | 0/30 |
| two `ping_request` round trips | 0/30 (0.24–1.48 ms apart) | 30/30 (49.2–50.6 ms apart) |
| one `client_command` (`REQUEST_STATS`) → `award_stats` | 0/30 (`award_stats` before `block_update`) | 0/30 |
| two `client_command` round trips, one after the other | **30/30, both Bots** (47.4–50.7 ms apart) | **30/30, both Bots** (49.2–50.6 ms apart) |

Why two `client_command` round trips work on vanilla: the first request
is handled at the start of a tick, before that tick sends what the
command changed. The second is sent only after the first answer arrives,
so it is handled at the start of the tick after, when the previous tick's
block and entity changes have been flushed. The answers are always one
tick apart (never the same `processQueuedPackets` pass). Pumpkin handles
both kinds of request once per tick, so two round trips of either kind
work there.

**Choice: the barrier is two `client_command` (`REQUEST_STATS`) →
`award_stats` round trips, one after the other.** Two ping round trips
do not work on vanilla, which answers pings off the main thread.

Limits:

- An overloaded vanilla may run a chat command after the tick the
  barrier waits for (`shouldRun`, above).
- Packets the server sends on its own clock can still arrive after the
  barrier: in 30 frozen trials vanilla sent `move_entity_pos` (4),
  `entity_position_sync` (1) and `player_info_update` (2) after it. They
  are the clocked packets below, not effects of the command.
- `award_stats` is the barrier's answer, so a window cannot compare it.

## Amendment, 2026-10-01 (#17): the barrier covers the packet phase

In the 30 trials above, each command ran before the next tick, as it
does when the server has time to spare. When it has none, a command sent
just before `Bot.sync()` is not covered:

- a chat command is a task in the server's task queue, and when the
  server is behind schedule, that queue can hold it for up to three ticks
  (`shouldRun`, above) while `REQUEST_STATS` is still answered at the
  start of each tick;
- live, the probe Group (`setblock` inside a window, vanilla on both
  sides) lost the `block_update` from one side's window in 8 of 80 plays.

So `Bot.sync()` covers what a Bot's own packets cause, handled in the
packet phase at the start of a tick. A command needs Control's barrier:
a marker command behind it in the same queue, then `Bot.sync()`
(`docs/research/2026-10-01-control.md`, The Control barrier).

## What arrives on a clock — live and javap

Two Bots, idle, 35 s with the world running and then 35 s frozen.

| Packet | Every | Frozen too | Vanilla | Pumpkin | Source |
|---|---|---|---|---|---|
| `set_time` (9 B) | ~1000 ms (20 ticks) | yes | yes | yes | `tickChildren`: `tickCount % 20 == 0` → `forceGameTimeSynchronization`, not gated by freeze |
| `keep_alive` | 15000 ms | yes | yes | yes | `keepConnectionAlive`, on the network thread |
| `player_info_update`, latency only (actions byte `0x10`, 36 B for two players) | ~30 s (601 ticks) | yes | yes | no | `PlayerList.tick`: `++sendAllPlayerInfoIn > 600` → `UPDATE_LATENCY` for all players |
| `move_entity_pos` for each tracked entity, other players included | 3000 ms (60 ticks) | yes | yes | no | `ServerEntity.sendChanges`: a position is sent when it changed **or** `tickCount % 60 == 0` |
| `entity_position_sync` for a tracked entity | now and then | yes | yes | no | `ServerEntity.createMovePacket`: when `teleportDelay > 400`, or on-ground changed |
| mob movement, sounds, entities entering view | often | no | yes | no | the world ticking |

With the world frozen, the watcher's player, seen by the operator, got
the same 9-byte `move_entity_pos` payload every 3000 ms; so did a
frozen passive mob. Pumpkin sent only `set_time` and `keep_alive`,
running or frozen.

## What this means for the heartbeat list

- `keep_alive` and `set_time` arrive on a clock on both servers and their
  names mean nothing else: they are left out of every window. `set_time`
  is compared by Groups of its own under a frozen world.
- `award_stats` is the barrier's answer: left out of every window. The
  barrier's request (`client_command`) is serverbound, and a window
  compares only clientbound packets.
- `player_info_update` and `move_entity_pos` also arrive on a clock on
  vanilla, but the same names carry the effects Groups test (a game mode
  change, an entity moving). Leaving them out by name would hide those,
  so they stay compared. A window that could catch one narrows itself to
  the packets it tests, for example
  `context.observe("minecraft:block_update")`. Telling a resend from a
  move needs the packet's schema (`move_entity_pos` has one since #20);
  whether to leave resends out is an open question in PLAN.md.
