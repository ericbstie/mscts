# ADR-0010: Groups compare play packets inside Observation windows

Status: accepted (2026-10-01). Refines ADR-0006's Masks rule (item 2) for
heartbeat packets and the barrier's packets.

## Context

A Comparison took every clientbound packet a Bot took. After a join, a
server keeps sending packets that have nothing to do with the mechanic a
Group tests: vanilla sends `set_time` every 20 ticks even with the world
frozen, `keep_alive` every 15 seconds, and more (see
`docs/research/2026-09-30-observation-window.md`). A Group that takes
packets until some packet arrives takes a number of these that depends on
the wall clock, so its Self-check fails. Packets a Bot never takes are
not recorded at all, so what a Group compares also depended on when it
stopped reading.

Masking `set_time` whole in every Group would hide the time of day, which
a player sees, against ADR-0006. Comparing only the packets a Group names
would never report an extra packet the Candidate sends (Pumpkin's
`hurt_animation` on `/damage`). Issue #18 weighed the three; the
maintainer chose windows.

## Decision

1. **`async with context.observe():` opens an Observation window.** In a
   Group that has windows, a Bot's play packets are compared only if they
   arrived (their Event's `t_ns`) inside one. Status, login and
   configuration packets are still compared whole. A Group with no window
   compares its whole stream, as before. Each side is windowed by its own
   Marks, `observe:open` and `observe:close` (not `observe:start` and
   `observe:end`: the Report times every `<name>:start` / `<name>:end`
   span under its name across all Groups, so those would add one timing
   mixing every Group's windows).
2. **A window can be narrowed to named packets**
   (`context.observe("minecraft:block_update")`); the names follow the
   open Mark's label. Then only those packets are compared inside it.
3. **Heartbeat packets are never compared inside a window.** They are
   listed in `compare.HEARTBEAT`, each with its reason, like a Mask:
   - `keep_alive` and `set_time`: sent on a clock whatever a Group does,
     on vanilla and on Pumpkin, frozen or not;
   - `award_stats`: the barrier's answer (item 4). The barrier's request,
     `client_command`, is serverbound, and nothing serverbound is
     compared.

   This is not a Mask: nothing is hidden from Groups that set out to
   compare these packets. Packets that arrive on a clock but whose names
   also carry gameplay effects stay compared, so they are not heartbeat
   packets: vanilla's latency-only `player_info_update` (every 601 ticks)
   and its position resend for every tracked entity (`move_entity_pos`
   every 60 ticks, even when nothing moved). A Group whose window can
   catch one narrows the window to the packets it tests.
4. **A window ends with a barrier, then a drain.** When the body
   completes, every Bot in play passes `Bot.sync`: it asks for its
   statistics (`client_command`, `REQUEST_STATS`) and waits for
   `award_stats`, twice, the second request sent once the first answer
   has arrived. Vanilla handles that request at the start of a tick,
   before the tick sends what changed, so one round trip is not enough.
   A play ping does not work either: vanilla answers it at once, off the
   main thread. Two round trips ended after every effect of a command on
   vanilla and on Pumpkin in 30 out of 30 trials each. Then the window's close Mark is recorded,
   and every Bot takes what has already arrived, without waiting.
5. **A Candidate that never answers the barrier fails the Group**: the
   timeout is the Bot's failure, so the Verdict is a `failed` Divergence,
   never `error` (H3b).
6. **What a window leaves out is no test case.**

## Consequences

- A gameplay Group's Self-check can be deterministic: it sets the world
  up before its window, and the window ends after everything its actions
  caused.
- Statistics cannot be compared inside a window, since `award_stats` is
  the barrier's answer.
- `set_time` is compared by no window. Groups for the time of day need
  another way to compare it (an open question in `docs/PLAN.md`).
- An overloaded vanilla may run a chat command later than the tick the
  barrier waits for (`MinecraftServer.shouldRun`), so a Fixture sent by
  command can, in principle, land after a window closed.
- Control (#17) calls `Bot.sync` after each command, and tick-indexed
  windows for tick-exact Groups (#23) build on these windows.
