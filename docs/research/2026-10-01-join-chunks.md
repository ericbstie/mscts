# Join and chunks: what a joined Bot has, and why the probe fails — 2026-10-01

Evidence behind #88. The issue's hypothesis was that `Bot.join()` returns before
the server has sent the chunk the probe Group's block is in, so a `setblock`
there sends no `block_update`. **The mechanism is real, and it is not what fails
the probe.** On vanilla the chunk is always in the first batch, which is what
`join()` waits for. The probe fails because `Bot.sync()` can end before the tick
that sends the change has flushed it.

Facts are **verified** in this container unless a line says *inferred* or *not
shown*: bytecode with `scripts/research/javap.py` (server and client jars of
26.3), live runs against vanilla 26.3 (the Reference) and Pumpkin nightly sha256
`b8382a8a…`. Live probes were scratch scripts (not committed) over the committed
`Bot`, `run_group`, `judge` and the probe Group, on a 4-CPU container shared with
other jobs. The server was not instrumented.

## What the vanilla client waits for before the world screen closes

(Javap, client `LevelLoadTracker`, `ClientPacketListener`; the player_loaded
section of `2026-09-26-join.md` has the rest.)

- `WaitingForPlayerChunk.isReady` holds when 30 s have passed (it lets the player
  in anyway), or the camera is outside the build height, or the player is a
  spectator or dead, or `playerSectionReady`: the renderer has compiled the
  section the camera is in. Nothing else counts. The client never waits for the
  rest of its view distance.
- `handleLevelChunkWithLight` puts the chunk into the client's chunk cache at
  once. `handleChunkBatchFinished` answers with `chunk_batch_received` at the rate
  it estimated.
- So a vanilla client is "loaded" with one chunk, its own. Chunks around it keep
  arriving, a batch per server tick, after it has sent `player_loaded`.

## What the server sends at join, and when

(Javap, server `PlayerChunkSender`, `ChunkMap`, `ChunkHolder`,
`MinecraftServer.tickChildren`.)

- A player's chunks are *pending* until a batch carries them. Each tick, last
  ("send chunks" in `tickChildren`), `sendNextChunks` makes at most one batch.
  It does nothing while `unacknowledgedBatches >= maxUnacknowledgedBatches`
  (1 until the first `chunk_batch_received`, then 10). The quota is
  `min(quota + rate, max(1, rate))`, so 9 chunks a tick at the start rate and
  at the 9 a Bot asks for (`CHUNKS_PER_TICK`).
- A batch holds the pending chunks that are *ready* (`ChunkMap.getChunkToSend`:
  the chunk's `sendSync` future is done and it has reached ticking status),
  nearest to the player's chunk first (`ChunkPos.distanceSquared`), up to the
  quota. A chunk that is not ready stays pending, and
  `ChunkMap.onChunkReadyToSend` marks it pending once it is.
- **A pending chunk gets no `block_update`.** `ChunkHolder.broadcastChanges`
  sends block changes to `ChunkMap.getPlayers(pos, false)`, which keeps a player
  only if `isChunkTracked`: the chunk is in its tracking view **and not
  pending**. The change reaches the player inside the chunk data instead.
- Packet order at join (live): `login`, `player_position`, `game_event`
  (`LEVEL_CHUNKS_LOAD_START`, 13), then `chunk_batch_start`, the chunks,
  `chunk_batch_finished`: a median 10 ms after `login` (at most 172 ms under
  load). At the default view distance 2 a Bot is sent 49 chunks: the first batch
  has the 9 nearest, then 9 a tick (about 50 ms each).

### Live, vanilla: what the first batch holds

20 joins on a quiet Instance, then 100 joins on one fresh Instance with 4
busy-loop processes beside it (loadavg 6): the first batch had **9 chunks and
held chunk (0, 0), the chunk of `1 -60 1`, every time**. The last of the 49
chunks came a median 230 ms after the first batch (200-460 ms under load). A
player's join pose is random once per world, inside the spawn radius, so its
chunk is (-1, -1) to (0, 0), and (0, 0) is always in the 3 x 3 around it. The probe
runs below say the same: (0, 0) arrived in the first batch on all 1,318 sides of
the 659 plays, the two failing plays included.

### Live, the mechanism (`setblock` into a pending chunk)

A Bot that holds back its first `chunk_batch_received` is sent only the first 9
chunks: the rest stay pending. Control set stone at `33 -60 1`, in chunk (2, 0),
which was not among them:

| | Vanilla | Pumpkin |
|---|---|---|
| chunks in the first batch | 9 (the 3 x 3 around the Bot) | 1 (chunk (0, 0)) |
| `block_update` the Bot got for the block while its chunk was pending | **0** | 1 |
| block state in the chunk data that arrived after the ack | 1 (stone) | 1 (stone) |

So on vanilla a change in a chunk the Bot has not been sent shows up only in the
chunk data, and a window that compares `block_update` sees nothing. That would
break a Group that sets a block outside the first 9 chunks right after a join.
Pumpkin sends the update anyway, so a Group that changes a block outside the
first batch right after `join()` would differ between the two: no `block_update`
on vanilla, one on Pumpkin, a difference made by when the chunk was sent and not
by the block. Pumpkin also sends only chunk (0, 0) before `join()` returns: its
first batch is one chunk, before `player_position`, then (0, 0) again, then 9 a
batch about 40–50 ms apart. So on Pumpkin more of the world is outside the first
batch. No Group in `tests/` changes a block outside chunk (0, 0) (`probe.py`
and `block_events.py` use blocks at x, z of 1 to 9).

## What `Bot.join()` waits for today

`join()` sends the handshake and `hello`, takes packets until play's first
`chunk_batch_finished`, and sends `player_loaded`. The first batch is what the
server sends first, nearest chunk first, so on vanilla `join()` returns with the
9 chunks around the Bot, at 120–400 ms; on Pumpkin with 1.

## The failing plays

Reproduced with the probe Group played the way the live test plays it: two fresh
Reference Instances, `run_group` on each in turn, `judge`. Each play logs its
barrier timing, and a failing play's two Transcripts are kept. 659 plays:

| Beside the probe | Plays | Not matching |
|---|---|---|
| nothing | 10 | 0 |
| 4 busy-loop processes | 60 | 0 |
| `mise run check` looping | 60 | 0 |
| `mise run check` looping, and a second probe loop (one with 4 busy-loop processes too) | 229 | 1 |
| `mise run check` looping, and a second probe loop | 300 | 1 |

Both failures came with `mise run check` and a second probe loop beside the
probe (loadavg 8–17 on 4 CPUs): 2 in 529 plays, none in the 130 with less load.
That is too few to rank the loads. For scale, the failure behind #88 (1 in 6 runs
of the 20-play pytest test) is the same order, about 1 play in 120.

The first failing play, side B (the second Instance), times in ms from the start
of its Transcript:

| ms | What |
|---|---|
| 122.9 | `login`, `player_position`, `game_event` 13 (watcher) |
| 126.6 | the watcher's first batch: 9 chunks, **(0, 0) among them**; `join()` returns |
| 462.3 | `observe:open minecraft:block_update` |
| 462.4 | Control sends `setblock 1 -60 1 minecraft:stone`, then its marker |
| 472.9 | the feedback and the marker's answer arrive, flushed with a chunk batch (the end of a tick) |
| 473.4 | Control's barrier, request 1 |
| **512.2** | answer 1 |
| 512.4 | request 2 |
| **512.6** | answer 2: **0.2 ms after answer 1** |
| 512.8–513.7 | the watcher's two round trips, answered at 513.4 and 513.7 |
| 513.8 | `observe:close` |
| **534.8** | the `block_update` (stone) reaches Control, flushed with a chunk batch: the end of the tick |

The second failing play, side A (the first Instance of its play):

| ms | What |
|---|---|
| 139.1 | `login`, `player_position`, `game_event` 13 (watcher) |
| 154.7 | the watcher's first batch: 9 chunks, **(0, 0) among them**; `join()` returns |
| 476.5 | `observe:open minecraft:block_update` |
| 476.7 | Control sends `setblock 1 -60 1 minecraft:stone`, then its marker |
| 480.1 | the feedback (the marker's answer at 480.4), alone, 3 ms after a chunk batch |
| 480.5 | Control's barrier, request 1 |
| **525.3** | answer 1 |
| 525.4 | request 2 |
| **525.6** | answer 2: **0.3 ms after answer 1** |
| 525.7–526.7 | the watcher's two round trips (answered at 526.4 and 526.7) and Control's own two for the window (526.3 and 526.6) |
| 526.8 | `observe:close` |
| **529.6** | the `block_update` (stone) reaches Control, flushed with a chunk batch; the watcher's Transcript has none |

What the two have in common:

- The watcher had chunk (0, 0) from its first batch, 336 ms and 322 ms before the
  window opened. Nothing was missing from its chunks.
- Every round trip from Control's first barrier request to the window's close,
  six answers in 1.4–1.6 ms, came before the server sent the change. The window
  closed 21 ms and 2.8 ms before that.
- In the other side of each play the answers were 50 ms apart and the
  `block_update` arrived inside the window.

## Why: the barrier's round trips can all be answered before the tick's flush

The barrier (`Bot.sync`) is two `client_command` (`REQUEST_STATS`) round trips,
the second sent only after the first answer. Its premise
(`2026-09-30-observation-window.md`) is that each is handled at the start of a
tick, so the second answer comes a whole tick after the first: after the tick
that broadcast the change has flushed it, at its end.

- **Javap, `PacketProcessor.processQueuedPackets`:**
  `while (!closed && !queue.isEmpty()) queue.poll().handle()`, on a concurrent
  queue the network threads add to. A packet that arrives while a pass is
  running is handled in that same pass, at the same tick start.
- `award_stats` is sent at once (the packet phase runs before the tick suspends
  flushing). A change the tick broadcasts is flushed only at the tick's end.
- **Live, both plays:** the answers came 0.2–0.7 ms apart, and the change at the
  end of the same tick. That fits a main thread that was still in the pass each
  time a request arrived: the pass runs while the queue is not empty, and the
  Bot's reply (0.1–0.2 ms) can beat the end of a handler on a loaded machine.
- **Not shown:** why the pass stayed open, since the server was not instrumented.
  A slow handler or a descheduled main thread fits; it is a reading of the
  javap and the gaps, not a measurement.
- Inferred, not shown: in the first play the command's feedback was flushed with
  a chunk batch, so it ran inside a tick, and its change went out a tick later.
  In the second the feedback came alone, between two ticks, and its change went
  out at the end of the next tick. Either way the barrier ended in that tick's
  packet phase.

The 30 quiet trials behind the barrier saw answers 47–51 ms apart (a tick). In
the 300 plays (600 sides) of the two probe loops that logged the watcher's pair:

| Watcher's gap between its two answers | Sides |
|---|---|
| under 1 ms | 4 |
| under 5 ms | 12 |
| under 10 ms | 13 |
| under 20 ms | 18 |
| under 40 ms | 39 |
| all (median 50.0 ms, largest 127.9 ms) | 600 |

One of the 13 under 10 ms lost the `block_update`. In the other 12 the stone had
arrived about 50 ms after the window opened, before the short pair, because the
window's earlier round trips had straddled the tick's flush as designed. A play
loses the packet only when every round trip between the command and the close
falls in one pass. That is rare (2 plays in 529 with load), but a Self-check that
plays the Group 20 times and runs five times in a row (100 plays) would fail in
about a third to a half of those batches at 0.4–0.8% a play.

Gaps between 5 and 20 ms also occur, most likely between legitimate ticks: a
server behind schedule starts the next tick at once. The watcher's pairs showed
5.4, 10.2, 12.2, 12.6, 17.0 and 17.5 ms, and Control's 9.1, 9.1 and 12.8 ms next
to 90 ms ticks. The 12 sides under 5 ms, which hold the failing pair, were all
0.1–3.6 ms.

## What this means for #88

- The hypothesis is disproved. `join()` already waits for the batch that holds
  chunk (0, 0), on vanilla and on Pumpkin, and (0, 0) was there 320–340 ms before
  the window opened in both failing plays. A wait in `join()` would not change
  the probe's failure rate.
- The mechanism behind the hypothesis is real (a pending chunk gets no
  `block_update`), but no Group in `tests/` reaches it.
- The failure is the barrier ending before the tick's flush. The issue's
  acceptance (the Self-check 20 of 20, five times in a row, under load) cannot
  hold until the barrier changes.

## Proposals

1. **Make #88 the barrier, and decide how.** Both options change what ADR-0010
   item 4 says ("two round trips ended after every effect"), whose evidence was
   a quiet machine.
   - *Gap-checked barrier* (server-agnostic, packet-level): `Bot.sync()` repeats
     the round trip until an answer comes at least a few ms (5 ms fits the data:
     gaps inside a pass were at most 3.6 ms, the others at least 5.4 ms)
     after the one before, up to a cap, so a server that answers on its network
     thread, with no tick in between, still ends. On the 600 sides it retries
     12 times (2%, one round trip each, about 50 ms) and catches the failing
     play. It is a threshold: a stall of more than the threshold inside a pass
     would get through.
   - *Command round trip as the second trip* (deterministic by structure): a
     command is a task the server runs between ticks, so its answer follows the
     tick's flush. `tellraw @s` needs an operator; `list` needs none (not run on
     a non-op Bot here). A Candidate that runs no commands has no barrier then,
     which sits badly with ADR-0001.
   - Recommended: the gap-checked barrier. Acceptance: the same load (a looping
     `mise run check`, two probe loops) with 300 plays and none not matching, and
     a unit test on the fake server (`tests/net/test_bot_sync.py`) whose answers
     come 0.2 ms apart.
2. **Keep the join-time chunk wait as a separate, optional issue.** Build it
   (`Bot.wait_for_chunks(radius)`, or a wait in `join()`) when a Group changes a
   block outside chunk (0, 0) or the first 9 chunks right after a join. On
   vanilla all 49 chunks are there a median 230 ms after the first batch (at most
   460 ms under load); on Pumpkin 50 chunks after a median 270 ms (at most
   420 ms).
3. **Docs:** ADR-0010 item 4 and the observation-window research note change with
   the barrier. This commit amends the note only.
