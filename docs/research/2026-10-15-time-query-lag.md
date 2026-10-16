# How many ticks a time query adds to a `mobs/*` sample — 2026-10-15

Evidence for #387. The `mobs/*` Groups step a frozen world with one `tick step <budget>`, and
when the Bot receives the packet a sample is about, Control runs `time query gametime`. The
sample is that answer less the game time before the step. While the query travels, the world
keeps ticking. Facts are **verified** live with `scripts/research/time_query_lag.py`
(vanilla 26.3, Pumpkin nightly 5b53f06, on a 4-CPU host) or with `scripts/research/javap.py`
on the 26.3 server jar, as each line says.

## The event: `set_time`

`set_time` comes every 20 ticks and carries a game time, so it is an event whose tick the
server itself names. No packet the `mobs/*` Groups sample on carries a tick.

- javap: `MinecraftServer.tickChildren` calls `forceGameTimeSynchronization` when
  `tickCount % 20 == 0`, before it ticks the levels. That sends
  `ClientboundSetTimePacket(overworld.getGameTime(), Map.of())`. So vanilla stamps `set_time`
  with the game time from before its own tick moves the clock on: a `set_time` stamped G
  comes from the tick that ends at G + 1.
- Live, both servers: in a frozen world, the first 8 bytes of the `set_time` payload (a
  Long) equal the answer to `time query gametime`.
- Live, both servers, stamped the same way: Control ran 300 queries back to back during a
  step, each after a random pause of up to 100 ms, and the probe read Control's own
  connection, where order is exact. A query is answered between ticks, so a `set_time` that
  follows an answer and carries that answer's game time was stamped before its tick moved
  the clock on, and one that precedes an answer with the same game time was stamped after.

  | Server | `set_time`s in the step | stamped before | stamped after |
  | --- | --- | --- | --- |
  | vanilla | 55 | 16 | 0 |
  | Pumpkin | 68 | 13 | 0 |

## What the query adds

The probe freezes the world, reads the game time and steps it 1,600 ticks. Each time the Bot
receives a `set_time` stamped G (`Bot.expect`), Control runs `time query gametime` through
`Control.run`, exactly as `mscts.groups.mobs_pathfinding` does, and gets A. The ticks the
query adds after the event's tick are A − (G + 1). Every answer came before the step ended.
"Under load" is a `mise run check` looping on the same host, started a minute before.

| Server | Load (1-min average) | Events | A − G | Ticks the query adds |
| --- | --- | --- | --- | --- |
| vanilla, at rest | 1.6–3.9 | 60 | 1 in 60 | 0 |
| vanilla, under load | 2.6–4.2 | 60 | 1 in 60 | 0 |
| Pumpkin, at rest | 0.8–1.5 | 60 | 2 in 60 | 1 |
| Pumpkin, under load | 1.4–2.5 | 60 | 2 in 60 | 1 |

- Vanilla answers the query before its next tick: a chat command is a server task, run
  between ticks (`docs/research/2026-10-03-tick-step.md`), and the round trip on one host is
  far shorter than the 50 ms between ticks.
- Pumpkin answers it one tick later, every time. In the burst above, Pumpkin answered 16
  queries with G + 1 right after a `set_time` stamped G, between the same two ticks, when the
  query had been sent before that `set_time` arrived. *Inferred, not verified*: Pumpkin runs
  a command only if it arrives early enough in the gap between ticks, and a query sent in
  reply to a packet arrives too late; its source was not reachable from this host.
- Neither server spread at all: the bias is a constant, 0 ticks on vanilla and 1 on Pumpkin,
  at the loads above. A busier host was not tried.
- `Control.run` returns once its marker is answered and its barrier is passed: 150 ms
  (median) after the event on vanilla, 200 ms on Pumpkin. A second event that reaches the
  Bot in that time is read only after it, so its sample is late by up to about 3 ticks on
  vanilla and 4 on Pumpkin. This hits a play only when two of its samples are a few ticks
  apart.

## What it means for the `mobs/*` samples

Every tick a Pumpkin play samples reads one tick later than vanilla's would for the same
event. It is a shift of the whole distribution by one tick, which a KS test over a sample
spread across tens of ticks is unlikely to reject, but a narrow one may. Vanilla against
vanilla shows nothing, since both sides add 0.

Ways to remove it, none implemented here:

- **Step in smaller chunks**, so that the answer can lag no further than the chunk. It changes
  each play's tick budget and run time.
- **Measure the query's lag on each Instance and subtract it.** One `set_time` during a step
  gives A − (G + 1), as above, on any server that stamps `set_time` as vanilla does (both do).
  The budget stays as it is, but a calibration query during the play delays reading the
  events that arrive while it runs, so it would need a step of its own before the mobs are
  summoned. It also assumes the lag stays the same for the whole play, which held for all
  240 events here.

The fix landed with #387, in the second way. Each play calibrated in a 40-tick step before the
mobs were summoned and subtracted the offset from every sample. The play's Bot is made an
operator and reads the game time itself, without waiting for the answer, so no event waits
behind an earlier read's `Control.run`. Since reads no longer wait, #404 moved the calibration
into the play's own step, on its first `set_time`, which saves about 2.5 s a play. Verified live with the probe's method on the Bot's own connection
(30 events each, serial and pipelined): its query adds 0 ticks on vanilla (1.5 ms median round
trip) and 1 tick on Pumpkin (50 ms), and both servers accept `op` and `deop` from Control.
