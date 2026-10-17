# Does a server answer the statistics requests after a Bot's action? — 2026-10-17

Evidence for #376. `GroupContext.step_after` takes the answers to the two statistics requests
a Bot sends after its action (`Bot.wait_until_handled`) as proof that the server has handled
the action, and only then steps (docs/research/2026-10-10-step-barrier.md). That was measured
on vanilla only. This note measures it on vanilla 26.3 and on Pumpkin nightly `b57d821`
(`mscts adapter status pumpkin`: commit `b57d821decdabcfadf300abfb2061ac0ad3cfd21`, sha256
`09a0a960…defc`, installed 2026-10-17), and reads where each server answers the request. Facts
are **verified** with `scripts/research/javap.py` on the 26.3 server jar, from Pumpkin's source
at that commit, or live with `scripts/research/stats_order.py`, as each line says.

## The action: placing a block

The probe needs an action whose effect the server sends back to the Bot from inside the
action's handler, so that the effect arriving before the answers shows the handler ran first.
Placing a block (`use_item_on`) is one on both servers:

- javap, vanilla: `ServerGamePacketListenerImpl.handleUseItemOn` calls
  `ensureRunningOnSameThread` first (offset 9), so it is handled in the same queue as
  `handleClientCommand`. At its end (offsets 620 to 650) it sends two
  `ClientboundBlockUpdatePacket`s, for the clicked block and for the block next to the clicked
  face, on every path past its reach checks.
- Pumpkin source: `handle_use_item_on` (`crates/pumpkin-core/src/net/java/play/use_item_on.rs`)
  sends `CBlockUpdate` for the placed cell from `run_is_block_place` (lines 256 to 273), when
  the placement succeeds, through `try_send_client_packet` (`entity/player.rs:3742-3748`).

## Where Pumpkin handles the request

From Pumpkin's source at `b57d821`:

- The connection's reader task pushes every play packet onto the player's
  `inbound_packets`, a `SegQueue` (FIFO), and handles none itself
  (`crates/pumpkin-core/src/net/java/mod.rs:301`, in `progress_player_packets`).
- `Player::tick` first calls `process_inbound_packets` (`entity/player.rs:2715-2716`), which
  pops up to 64 packets in order and calls `handle_play_packet` on each, inline
  (`player.rs:2640-2712`).
- `handle_play_packet` handles `use_item_on` (`net/java/mod.rs:1014-1019`) and
  `client_command` (`mod.rs:833-834`) inline. `REQUEST_STATS` calls `Player::send_stats`
  (`net/java/play/client_command.rs:52-55`), which queues `award_stats` with
  `try_enqueue_packet` (`player.rs:3357-3382`), the same per-connection outgoing FIFO the
  placed cell's `block_update` goes through.
- Only some packets get a task of their own (`server.spawn_task`): `chat_command`, the signed
  `chat_command`, `chat` and `chat_session_update` (`mod.rs:760-825`, `1041-1052`). A
  statistics request is not one of them.

So Pumpkin, like vanilla, handles a player's actions and its statistics requests in one queue,
in the order they came, and answers each request as it handles it.

## Live

`scripts/research/stats_order.py` boots one Instance in creative mode, puts the digger where
`blocks/place` does, sets a stone block south of it and freezes the world. Each round, the
digger places stone on top of that block, then `context.step_after(digger)` runs, then Control
puts air back. A round is in order when the placed cell's `block_update` reached the digger
before the last `award_stats` that `wait_until_handled` took, by the Transcript's stamps (frames
of one socket read are stamped a nanosecond apart, in the order they came). The four runs went
one after another under one live-lock hold, on a 4-CPU host:

```sh
mise exec -- uv run python scripts/live_lock.py -- \
    mise exec -- uv run python scripts/research/stats_order.py pumpkin 100 /tmp/out
mise exec -- uv run python scripts/live_lock.py -- \
    mise exec -- uv run python scripts/research/stats_order.py pumpkin 100 /tmp/out --stress 4
```

and the same with `vanilla`. `--stress 4` runs four busy loops beside it.

| Server | Load | Rounds in order | Effect, ms after the place (median, range) | Last answer after the effect, ms (max) |
| --- | --- | --- | --- | --- |
| Pumpkin | idle (1-min load 3.2 at the start) | 100 of 100 | 49.6 (22.4 to 54.6) | 0.00 |
| Pumpkin | `--stress 4` (4.2 at the end) | 100 of 100 | 49.7 (32.4 to 60.4) | 0.00 |
| vanilla | idle (4.2 at the start) | 100 of 100 | 50.6 (47.4 to 213.1) | 0.72 |
| vanilla | `--stress 4` (4.9 at the end) | 100 of 100 | 51.5 (41.5 to 72.8) | 5.16 |

- In every round `wait_until_handled` took exactly two `award_stats`, so no server sent one
  unasked during the proof.
- On Pumpkin, the effect and both answers came within 0.01 ms of each other in every round:
  it handled the place and both requests in one `process_inbound_packets`, in one tick. That
  is the once-a-tick answer #169 describes.
- No round was out of order, so the probe saved no Transcript.

So on both servers the answers to `wait_until_handled` come after the effect of the Bot's
earlier action, and `step_after`'s proof holds on Pumpkin at `b57d821`.
