# ADR-0010: Groups compare play packets inside Observation windows

Status: accepted (2026-10-01). Refines ADR-0006's Masks rule (item 2) for
heartbeat packets and the barrier's packets. Amended 2026-10-01 (#17):
Control's barrier, below. Amended 2026-10-02 (#88): the barrier ends only
after a tick has passed, below. Amended 2026-10-02 (#105): a window can
end at a packet's arrival, below. Amended 2026-10-03 (#165): the latency
broadcast is a heartbeat packet, below.

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
   vanilla and on Pumpkin in 30 out of 30 trials each, on a quiet machine
   (the 2026-10-02 amendment replaces this: two round trips are not
   enough under load). Then the window's close Mark is recorded, and every
   Bot takes what has already arrived, without waiting.
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

## Amendment (2026-10-01, #17): Control's barrier

`Bot.sync` alone does not cover a command. Vanilla runs a chat command as
a task on the server's queue, which a server behind schedule holds for up
to three ticks while it still answers the barrier's request at the start
of each tick. A probe Group with `setblock` inside a window lost the
`block_update` from one side's window in 8 of 80 plays on vanilla
(`docs/research/2026-10-01-control.md`, "The Control barrier").

1. **Control ends each command with a marker, then the barrier.** After
   the command, `control.run` sends `tellraw @s "<token>"`, with a token
   of its own (a fixed prefix and a count), waits for the `system_chat`
   holding the token, then calls `Bot.sync`. It returns every
   `system_chat` that arrived from the command to the end of the barrier,
   except the marker's answer. They are evidence for the Group, never
   compared.
2. **On vanilla this is exact.** The marker is a task on the same queue,
   behind the command, so its answer means the command has run: 0 of 80
   plays lost the `block_update` with the marker.
3. **On Pumpkin it is not, and that is a difference from vanilla.**
   Pumpkin runs each command as its own task, at the same time as the
   others, so a command that takes more than about a tick longer than the
   marker can land after `run` returns (a `fill` of 28,830 blocks
   answered after its marker 18 times in 18; the `block_update` of a
   `setblock`, never in 120). Even a `setblock`'s answer came after the
   marker's in 71 runs of 100, though always before the barrier ended,
   so `run` returns what arrived until the barrier ended, not only what
   came before the marker's answer. That is a real difference, and it
   shows where it lands.
   Groups keep their setup commands before their windows, and small.

This replaces the last consequence's "calls `Bot.sync` after each
command", and answers the one before it for commands sent through Control.

## Amendment (2026-10-02, #88): the barrier ends only after a tick has passed

Item 4's barrier is two round trips, on the premise that vanilla answers a
request at the start of a tick, so the second answer comes a whole tick
after the first. That held on a quiet machine. Under load, a `setblock`'s
`block_update` reached a Bot after its window had closed in 2 of 529 plays
of the probe Group (`docs/research/2026-10-01-join-chunks.md`). In both, the
barrier's six answers came within 1.6 ms. Vanilla's `PacketProcessor`
handles every queued packet in one pass at the start of a tick, a request
that arrives during the pass included, so two requests sent back to back
can be answered together, before that tick has sent anything. Of 600 sides
measured, 12 had a pair of answers closer than 5 ms.

1. **A pair of answers ends the barrier only if they arrived at least
   `TICK_GAP_S` (5 ms) apart.** `Bot.sync` sends a request, takes its
   answer, sends another and takes that: a pair. It compares when the
   answers arrived (`Connection.last_arrival_ns`), not when the Bot took
   them. Answers from one pass came 0.1 to 3.6 ms apart, and answers from
   different ticks at least 5.4 ms.
2. **A pair that arrives closer is followed by a wait and another pair.**
   The Bot waits `TICK_GAP_S`, for the pass to end, then asks again. The
   wait goes between pairs. Between the two requests of a pair it would put
   the answers `TICK_GAP_S` apart whatever the server does, and the gap
   would prove nothing.
3. **The barrier gives up after `SYNC_MAX_TRIPS` (6) requests, three
   pairs.** `Bot.sync` returns and leaves the Mark `sync:capped <Bot name>`
   (`bot.SYNC_CAPPED`). A server that answers on its network thread, with no
   tick between, never shows a gap, and must not hold a Bot for ever.
   Compare reads only `observe:` Marks and the Report times only
   `:start` and `:end` Marks, so the Mark changes no Verdict.
4. **It is a threshold.** A stall longer than `TICK_GAP_S` inside one pass
   would get through.

A pending chunk is a second way for a block change to leave no
`block_update`. Vanilla sends none for a chunk it has not yet sent to a
player: the change reaches the Bot in the chunk data. Pumpkin sends one
anyway. `Bot.join` returns after the first chunk batch. It held chunk
(0, 0) on vanilla in every join measured (1,318 of 1,318), and on Pumpkin
in the runs made. So
**Groups change blocks only in chunks a Bot has had since join**, for now
chunk (0, 0): blocks with x and z from 0 to 15. A Group that needs more
waits for the chunks it needs (not built yet).

## Amendment (2026-10-02, #105): a window can end at a packet's arrival

Item 4's barrier lets in whatever the server sends until the barrier's
answers: for a join, that was 1 to 6 chunk batches and the mobs walking into
view, so two vanilla joins matched in 2 of 84 plays (#30's measurement). A
join's first chunk batch is the same on every Instance; what follows it
depends on timing.

1. **`observe(until=<packet>)` ends the window at that packet's arrival,
   with no barrier.** Its close Mark is stamped a nanosecond after the
   first such play packet arrived at a Bot other than Control's. The body
   must last until it has arrived (`bot.join()` does); if none arrived,
   the Group fails (a Candidate's `mismatch` with a `failed` Divergence,
   the Reference's `error`).
2. **Frames that one socket read completes are stamped a nanosecond
   apart, in order.** Before, they shared a stamp, and vanilla sends a mob
   bundle and `player_info_update` in the same read right after
   `chunk_batch_finished`, so a Mark could not fall between them: 6 of 100
   plays differed. With distinct stamps, 160 of 160 plays held the same
   packet names, counts and chunk positions on two vanilla Instances.
3. **`Control.leave()` closes Control's Bot;** the next `run` joins a new
   one behind the barrier. A Group whose window holds a join sets its
   Fixture, leaves (so the joining Bot does not see Control's player),
   waits with `mscts.settle`, and rejoins Control to undo the Fixture.

## Amendment (2026-10-03, #165): the latency broadcast is a heartbeat packet

Item 3 kept vanilla's latency-only `player_info_update` compared, because
leaving `player_info_update` out by name would hide the player list
changes Groups test. A join-until window, which names no packets, then held
one on one side only: it arrives every 601 ticks on the server's own
counter, so whether it falls inside a window is timing
(`docs/research/2026-10-03-latency-broadcast.md`).

1. **A heartbeat packet can be told apart by its first bytes.**
   `compare.HEARTBEAT_PAYLOADS` maps a packet name and the bytes its
   payload starts with to the reason, beside `compare.HEARTBEAT`, and
   `compare.is_heartbeat` says whether a packet is either. A
   `player_info_update` starts with its set of actions, one byte; `0x10`
   is `UPDATE_LATENCY` alone, which only `PlayerList.tick` sends.
2. **Every other `player_info_update` is still compared.** A join, a game
   mode change or a listing change sets other actions, so its first byte
   differs.
3. The position resend (`move_entity_pos` every 60 ticks) stays compared,
   as item 3 says, until PLAN.md's open question on it is decided.
