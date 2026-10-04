# Chunk loading: which chunks vanilla sends a player, and when — 2026-10-04

Evidence behind #33's `chunks` Groups. Facts are **verified** with
`scripts/research/javap.py` on the 26.3 server jar (client jar where a line
says so), or on two fresh vanilla 26.3 Instances where a line says *live*.

## Which chunks a view holds

- `ChunkTrackingView.contains(x, z)` calls `contains(x, z, true)`, which calls
  `isWithinDistance(cx, cz, distance, x, z, true)`. With `true`, the offset
  allowed for free is 2: `dx = max(0, |x - cx| - 2)`, `dz` likewise, and the
  chunk is in the view when `dx * dx + dz * dz < distance * distance`.
  `Positioned.forEach` walks the box `centre ± (distance + 1)`.
- So view distance 2 is the 7 by 7 square around the centre. *Live*: a
  player joining at view distance 2 was sent exactly those 49 chunks.
- `ChunkMap.getPlayerViewDistance` is `Mth.clamp(requestedViewDistance, 2,
  serverViewDistance)`. Nothing adds 1 on the way from `server.properties`
  (`PlayerList.setViewDistance` → `ServerChunkCache.setViewDistance` →
  `ChunkMap.setServerViewDistance`, which clamps to 2..32).
- The client keeps chunks within `max(2, distance) + 3` of its centre
  (`ClientChunkCache.calculateStorageRange`, client jar) and drops a chunk
  sent outside that range ("Ignoring chunk since it's not in the view range").

## When they are sent

- `ChunkMap.applyChunkTrackingView` sends `set_chunk_cache_center` only when
  the centre changed, then works out `ChunkTrackingView.difference(old, new)`:
  each chunk that left the view is forgotten at once (`forget_level_chunk`),
  and each that entered it is queued for sending.
- `MinecraftServer.tickChildren` sends the queued chunks
  (`PlayerChunkSender.sendNextChunks`, "send chunks") whether or not the tick
  rate manager runs normally: `/tick freeze` does not stop chunk sending.
- A batch holds the pending chunks nearest the player
  (`collectChunksToSend`: `Comparators.least(quota, distanceSquared)` over
  `pendingChunks`), and a chunk becomes pending only once it is loaded
  (`markChunkPendingToSend(LevelChunk)`). So the join's first batch is the 9
  nearest chunks that are *ready*: the 3 by 3 around the player only when all
  9 are. A Group counts the chunks a Bot already holds (`Bot.chunks`) rather
  than assume what the first batch held.
- `sendNextChunks` never sends an empty batch, so nothing tells a player that
  its view is complete. A Group waits for the chunks it expects.
- *Live*: the join's chunks were all sent 250 to 400 ms after the join; a
  teleport's 500 to 700 ms after it. `set_chunk_cache_center` came about 90 ms
  after the teleport's `player_position`.

## What differs between two vanilla Instances

- *Live*: after a teleport, which chunks each batch held, and their order,
  differed between two Instances (one: batches of 3, 4, 9, ... chunks; the
  other: 5, 1, 9, ...): *inferred*, a chunk is sent once it is ready. The first
  join of a fresh Instance differed the same way (4 then 1, against 5). So a
  `chunks` window does not compare `chunk_batch_start` or
  `chunk_batch_finished`.
- *Live*: the server keeps where a player left, so its next join starts
  there. A Group that moves a player puts it back before it leaves.
