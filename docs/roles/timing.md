# Timing specialist

**Lane:** what happens on which tick, and in what order. **Model:** opus.
**Owns the core area:** `net.py`, `bot.py`, `settle.py`, `group.py`,
`transcript.py`. Other lanes ask the lead for changes there.

**Issues** (`lane:timing`): #115 and #117 (audit fixes, first), #23
tick-exact Groups, then #37 falling blocks, #38 fluids, #39 redstone
timing, #40 pistons, #41 hoppers, #42 piston glitches, #46 entity motion,
#57 hunger, #58 effects, #63 day cycle, #64 weather, #66 command feedback.

## What this lane knows

- The barrier (`Bot.sync()`) is `SYNC_REQUESTS` (3) statistics round trips,
  each sent 5 ms after the last answer (ADR-0010 and its amendments). Two
  would prove a tick; the third covers one unasked `award_stats` (#169).
  Under load vanilla can answer two in one pass; a stall in our own event
  loop can fake a gap (audit 2026-10-02 H1, #115).
- A change to a barrier or a window is done when its Self-check passes 20
  of 20 five times in a row under `repeat.py --stress`, with a javap account
  of every queue it crosses. Run it as
  `MSCTS_SELFCHECK_REPEAT=20 mise exec -- uv run scripts/repeat.py --times 5 --stress --live-lock --stop-at-first-failure --failure-log <scratch>/first-failure.log --deadline <ISO time with Z> -- <Self-check node id>`:
  the series ends at the first failing run, keeps that run's output, and starts no run
  after the deadline (the same time again after a restart, so the series has one
  budget). Each line starts with the time the run ended.
- A window or timing spec gets a 20-play live probe
  (`scripts/research/probe_loop.py`) before its brief.
- Frames of one socket read are stamped a nanosecond apart (#112), so a
  packet behind the window's closing packet stays outside it.
- Pumpkin runs each `chat_command` in its own task: its answers come out of
  order. Measure order on both servers (100 runs) before fixing an order
  contract.
- Never cancel a Bot operation from outside: bound it with its `timeout_s`
  (a cancelled status poll leaked its socket).
- A fake server answers like the real one by default (a barrier's answers a
  tick apart), or fakes hide timing bugs.
- `repeat.py --stress` runs at most the default `--stress-workers`
  (nproc), unless an issue says otherwise: more slows every other agent on
  the host.
- Live tiers assume a load average of at most about the CPU count. Above
  that, a Reference timeout is the host's fault, not a Verdict: a Bot
  operation's 10 s bound stays fixed, because scaling it with the load
  would let a hanging Candidate score better (#134).

## Log

Newest first: one line per lesson, with the issue it came from.

- #463: a dead player gets entity event 60 at `deathTime` 20, about 1 s after the death, because `LivingEntity.tickDeath` sends it with `sendToTrackingPlayersAndSelf` and a player ticks in real time in a frozen world. `PlayerList.respawn` removes the old player before it sends `respawn`, so no event 60 follows the respawn.
- #463: count the barrier answers between a death and the Bot's respawn request, because under load each one costs a tick. In `player/fall` a step after the lethal landing held the request back about 7 ticks (a median of 598 ms after the death with the step, 247 ms without, at a load of 6), and the dead player is shown nothing meanwhile.
- #463: a death that ends a stepped Group's window ends it with `until=player_combat_kill` and an `expect` after the move, not a closing barrier, so a server that kills a few ticks late is still compared. Its tick is not, and what `ServerPlayer.die` sends after the kill packet (entity event 3) and the health it leaves are in no window (#487).
- #463: a mutant that makes a cached Group play raise needs a one-test selection: `functools.cache` does not cache the exception, so every test of that Group replays it past the sweep's timeout.
- #463: a check on what a Bot operation takes inside itself (`respawn`, `sync`) cannot be written in a Group: the Group sees only what `expect` returns, and the Transcript is private to GroupContext. Such a check needs a keyword on the Bot operation.
- #461: a Group that changes the world's weather sets `advance_weather false`, then `weather clear`, then waits for the fade, before the world is frozen or a Bot joins (`calm_weather` and `until_the_weather_fades`). A fake that answers `time query gametime` is `PlayerServer`, not `BlocksServer`.
- #456: the probe Self-check `test_a_tick_exact_group_self_checks_20_of_20` takes about 250 s a run under `--stress --live-lock` on 4 CPUs at a load of 5 to 6, so 35 runs take about 2.5 h without lock waits. Another worker's live run adds 5 to 10 min to each run it waits behind.
- #454: a window opens after the later Bot's last barrier answer, so a Bot whose barrier ended first can have read a setup packet that is still queued. A Group that counts or waits for a periodic packet takes what that Bot has read first (`Bot.drain`), then acts and counts. Vanilla does this too: a statistics answer and the 20-tick `set_time` leave in one flush.
- #454: a flake that one play per process never shows can need the host loaded the way `mise run check` loads it. Play many plays side by side (a parametrized probe under `pytest -n 8` inside `repeat.py --stress`): 3 of 176 plays came up short on main, against 0 of 35 for the test alone.
- #454: a fake makes a cross-Bot ordering race happen every time when it writes the packet together with one Bot's barrier answer and delays the other Bot's answers (`TimeServer.time_behind_answers`, tests/group/test_time.py).
- #345: a player's air (`set_entity_data` index 1) goes down 1 a tick of the player's own, so it is an in-band clock of player ticks. A window that opens while the air is full and ends on a one-off packet (the death) compares the ticks between drowning hits exactly; a window opened after a hit starts a tick or two late on one Instance. `set_time` is no clock for this: its phase against the hits differs per play.
- #345: a check that a periodic packet came in time reads the order of the Bot's own packets (the next X before the next Y), never the clock when the Bot read a packet. A server catching up runs the ticks it owes back to back, and a stalled Bot reads late. A fake that models the catching up runs its burst ticks with no `await asyncio.sleep(0)`.
- #40: a sticky piston that loses power while its block is at progress 0.5 retracts with block event type 2 and leaves the block behind, so a 1-tick pulse is a `setblock` between stepped ticks. `moving_piston` states are set without flag 2 and never sent. A slime block on grass drags the grass: those builds sit at y -59.
- #39: for several 20-play Self-checks, run one `mise run test:selfcheck -- <node id>` per Group in a script. Each takes the live lock on its own, so other workers' short runs fit between them.
- #376: Pumpkin (nightly b57d821) handles a player's play packets, statistics requests included, in one FIFO from `Player::tick`, and answers `REQUEST_STATS` there; only chat commands, chat and the chat session get a task of their own. `step_after`'s proof held 100 of 100 on Pumpkin and on vanilla, idle and under `--stress 4` (docs/research/2026-10-17-stats-order.md, `scripts/research/stats_order.py`).
- #356: an Observation window opens a nanosecond after the latest last barrier answer of a Bot other than Control, so a frame a Bot read with or after that answer is inside the window. Stamping the open Mark at "now", after Control's barrier, lost those frames. An `until` window refuses a second Bot besides Control in play: it would need an open Mark per Bot (#424).
- #356: an `until` window cannot tell whether its end packet came from the body. A periodic packet (a burn or drown hit) can end it before the body's action; on vanilla `check_gap` guards that.
- #356: a fake sends periodic packets at vanilla's period (fire and lava every 10 ticks, dry grass and drowning 20, freezing 40) and stops where vanilla stops. A fake that hurt every tick put a hit between a window's open and the Group's teleport once the open moved earlier.
- #423: a Self-check's time limit is a `timeout` mark on each case (`support.selfcheck.with_time_limits`): pytest-timeout reads the closest mark when the test starts, so a fixture or a module mark cannot give one Group more time. A Group that takes more than 90 s a play goes in `SLOW_PLAY_LIMIT_S` with its play time on main and the load average (`player/starvation`: 112 s a play at 3 plays and 103 s at 20, limit 225 s).
- #410, #419: `timeout_s` bounds each Bot operation, not the play. A test that expects a TimeoutError from one hang uses `HANG_LIMIT_S` (tests/group/test_control.py), which only the hang reaches, runs a slower earlier step (`STALL_S`), and asserts the hang was reached: the commands the server saw end with the hung step and the undo, or the marker or barrier request it saw. For a hang after the join, stall the join with `late(handler, STALL_S)`; `ControlServer(stalls=...)` delays chat commands only.
- #410: a fake that hangs answers again where the Group undoes, or the undo times out and `pytest.raises(TimeoutError)` accepts it by accident.
- #418: a live-lock hold interrupted before it has the lock must not run the release. Take the lock before the `try` whose `finally` releases it.
- #368: `@e` selectors carry `Entity::isAlive`, so `execute if entity @e[...]` fails the moment `kill` runs, and a killed body stays 20 ticks (`LivingEntity.tickDeath`). To know the bodies are gone, wait until a Bot beside them tracks only players (`_world.remove_tagged_until_gone`).
- #368: Pumpkin (nightly f1c0871) has no `/execute` (`command.unknown.command`), and drops a killed mob's loot with `mob_drops` false.
- #360: `Bot.wait_until_handled` proves the server handled what a Bot sent in about one packet pass (about 50 ms); use it before a step. Use `sync` (3 passes) only when you need everything the action caused. The proof is measured on vanilla only (#376).
- #411, #360: run a family's live stress series with `repeat.py --stress --live-lock --stop-at-first-failure --deadline <ISO time with Z>`, never under an outer `live_lock.py`: that holds the lock to the last run (3.3 h in train 38), and a short run queued behind it waits for all of it. With the flag it waits for at most one run (`scripts/research/lock_wait.py`: 9.1 s against 1.0 s behind a fake series of six 2 s runs). A timing comparison, which must not be disturbed, holds the lock across its runs on purpose. For runs past the 2 h background cap, detach the driver with `setsid` and prefix watcher lines with the file name. After a container restart, start the series again with the same `--deadline`, and `--times` lowered by the runs that ran (the report and the timestamped lines say how many).
- #37: in a frozen world `ChunkMap.tick` still runs `ServerEntity.sendChanges` every server tick, so an entity's periodic `move_entity_pos`, `set_entity_motion` and `entity_position_sync` follow the wall clock and cannot be compared tick-exact. One-off packets (`add_entity`, `remove_entities`, a dirty `set_entity_data`) stay on their step.
- #37: a packet belongs to step k when it arrives between the Marks `tick:<k-1>` and `tick:<k>`. Count steps from the Marks, not from where a listing prints them. A 20-play probe that matches does not predict the Self-check: give a reason for every entity packet a tick-exact Group compares.
- #37: a block that loses its support pops inside the `setblock` command that removes it; its `section_blocks_update` arrives in the next frozen tick, before the step. An item moves at random from the tick after it spawns: end the window on the drop tick and kill the item before the next window.
- #38: a block or fluid tick scheduled in a frozen world is saved with the chunk and runs in the next play. A tick-exact Group that schedules ticks ends each window with none due, and clears with `fill ... strict` (no neighbour updates) before a plain fill.
- #38: fluid Self-checks are slow: 20 plays of `fluids/lava-spread` (92 steps a side) take about 21 min, all four `fluids/*` Groups about 65 min.
- #360: in vanilla 26.3 a Bot's action handlers and `handleClientCommand` share one server-wide FIFO (`PacketProcessor.packetsToBeHandled`), drained every tick even while frozen; chat commands bypass it (`server.execute`). One answered `client_command` proves every earlier action of that Bot was handled (docs/research/2026-10-10-step-barrier.md, on PR #367).
- #360: a per-step barrier multiplies: count a play's steps times the barrier's round trips before adding one; `player/fall` (58 steps) overran the Self-check's 90 s a play under stress.
- #57: a respawned player ignores damage until the server has read its `player_loaded` (`ServerPlayer.isInvulnerableTo`): run `/damage` after a barrier, for example inside the window.
- #57: to wait until "nothing more comes" from a player's own ticks, count `set_time` packets: vanilla sends one every 20 ticks, frozen or not, so 6 of them span at least 100 ticks. `context.step` costs about 300 ms a step.
- #57: food, saturation and exhaustion change in the player's tick, on the wall clock: compare the order of the changes (`exact`), not the tick they land on. Set food exactly with a kill and respawn, the Hunger effect for a counted number of ticks, then `/damage generic`.
- #129: what crosses a window's edges is measured per window with
  `scripts/research/probe_window_edges.py`: setup packets inside the
  window, the command's packets after the close, and the margin before
  the open. On `main`, a setup change reached the builder at least 31.6 ms
  before the open at a load of 11 to 17; the barrier before the open
  (#141) makes that 123 ms, and stamps it before the open by construction.
- #129: `section_blocks_update.blocks` comes from a fresh
  `ShortOpenHashSet` per section and broadcast, so its order is set by the
  positions changed; it varies only if a broadcast merges other changes.

- #126: asyncio accepts a connection in one loop turn and attaches it to
  the `Server` in a task of its own the next; attached after
  `Server.close`, it leaks (`_attach` asserts the server is open). A fake
  stops reading its listener (`loop.remove_reader`), waits two turns, then
  closes. Find such windows by stepping a raw client k loop turns, k = 0..7.
- #127: `Connection.close` closes its writer in a `finally`, so a second
  cancel during the reader wait no longer leaks the socket.
- #123: a test that cancels after a fixed sleep races connect under load:
  wait on an Event the fake sets at the state the test needs. Map
  cancellation points by cancelling after k loop turns against a plain
  blocking listener, and check bytes received, EOF, leftover tasks and
  ResourceWarnings at each k.
- #123: once connected, a Bot sends packets back to back without yielding
  (`StreamWriter.drain` yields only when the transport is closing or
  paused), so "cancelled between two sends" needs a paused or closing
  socket.
- #63: an operator Bot hears Control's commands as admin chat. To compare chat in a window where Control acts, `deop` the Bot before it and `op` it after.
- #63: to compare when something happens on the wall clock (the 50% night skip, about 100 player ticks), add a read window before it is due, not only the order of what comes.
- #63: counting `set_time` to span N ticks after an action needs one more, since the first counted may be sent before the action. Wait on any `set_time`, not only one with an empty clock.
- #63: a player's advancements and bed spawn point persist in playerdata: revoke the advancement and move the spawn point off the bed so every play is a first night.
- #403: `free_endpoint` gives each Instance its own random host, so two Instances can share a port number (about 1 pair in 14 000 here). A test or fake that tells sides apart keys on the whole Endpoint, never on `.port`.
- #427: a Bot operation's TimeoutError says `<bot> waited <limit> s for <what>`. `Bot._operation` takes what the operation waits for. The outer operation's text wins over an inner `expect`'s, because the outer `asyncio.timeout` is armed first and fires first. Only a TimeoutError that already has text passes through. `run._describe`'s "no answer within" fallback serves only a bare TimeoutError from elsewhere (`Bot.connect`, a Group).
- #427: to test a send's timeout text, join first, then monkeypatch `Connection.send` and `Connection.send_all` to hang. The join must fit inside the Bot's `timeout_s`, so use 0.2 s, not 0.05 s.
- #376: to prove the server handled an action, pick one whose effect it sends from inside the handler. Placing a block (`use_item_on`) works on both servers. A dig's `block_update` comes from the tick on vanilla, so it proves nothing there.
- #41: a hopper moves in the block entities' part of a tick, after the players' part; an open menu sends the change in the next server tick, which a frozen world runs before the step's barrier ends. An item a hopper moves on the step of tick N shows on tick N: step N ticks, not N+1.
- #41: after a Bot closes a chest, step the world 5 ticks (`fast_forward(control, 5)`): the chest's recheck of its openers is still due and would run in the next play.
- #41: a summoned item entity gets `Rotation:[0f,0f]` (its constructor turns it at random) and `NoGravity:1b` (stepped ticks tick entities). An item summoned inside a full block is pushed out at a random speed: never compare one there.
- #41: an item in a hopper's bowl is taken by `entityInside` in the item's own tick, before the block entities, whenever the hopper is off its wait, full block above or not. A full block above shows only as a pickup a tick late, after a wait ends.
- #487: a window that holds a player's death waits for the death in its body and closes at the barrier, not with `until=player_combat_kill`: `ServerPlayer.die` sends entity event 3 right after the kill, and the tick sends `set_health` 0 and the entity data after it. The barrier costs 3 answers: `player/void`'s respawn request leaves 298 ms (median) after the death, against event 60's 1000 ms.
- #473: `_world.respawn_in_a_window` is the one respawn helper for a dead Bot whose window compares `entity_event`.
- #487: Pumpkin (9c04f71) sends entity event 3 before `player_combat_kill`, and no `set_health` 0 after a death.
