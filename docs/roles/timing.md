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
  of every queue it crosses.
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
