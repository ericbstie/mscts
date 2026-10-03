# `blocks/fill` under load: what crosses a window's edges — 2026-10-03

Evidence behind #129 (`blocks/fill` failed its Self-check once in 20 runs,
at a load average of 32 to 43 on 4 CPUs) and #134 (`blocks/setblock` timed
out on the Reference at a load of 35 to 40). Bytecode was read with
`javap` from the 26.3 server jar.

## The order of `section_blocks_update.blocks` is no source of flakiness — javap

- `ChunkHolder.blockChanged` adds each changed position to the section's
  `ShortSet`, which it creates as a new `ShortOpenHashSet` when the
  section has none. `ChunkHolder.broadcastChanges` sends a `block_update`
  for a set of one, or else `new ClientboundSectionBlocksUpdatePacket(
  SectionPos, ShortSet, LevelChunkSection)`, which writes the set in its
  iteration order, and then clears the section's entry.
- An open hash set's iteration order is set by which positions it holds
  and by the order they were added. Neither depends on the run, so the same
  commands give the same order on two Instances. A one-off mismatch in that
  list means the set held different positions, for example a setup change
  broadcast together with the command's own.

## What crosses a window's edges — measured

`blocks/fill` played Reference against Reference 15 times, at
`repeat.py --stress --stress-workers 16`, which put the 1-minute load at 11
to 17 on 4 CPUs. For each of the 8 windows on each side of each play, the
probe (`scripts/research/probe_window_edges.py`) records:

- **leaked**: a compared packet inside the window that arrived before the
  builder sent its command, so the command cannot have caused it;
- **late**: a compared packet of the builder that arrived after its close
  Mark and before Control started the next case's setup;
- **margin**: the open Mark minus the arrival of the last compared packet
  before it (the setup's last change).

| Code | Plays matching | Windows leaked | Windows late | Margin, min / median |
| --- | --- | --- | --- | --- |
| `main` at `03c18de` | 15 of 15 | 0 of 240 | 0 of 240 | 31.6 / 48.3 ms |
| #181 (barrier before the open) | 15 of 15 | 0 of 240 | 0 of 240 | 123.0 / 148.1 ms |

On `main`, Control's barrier is all that stands between the setup's last
change and the open Mark. The builder, which receives that change too,
only drains what has already been stamped. The setup's change reached the
builder at least 31.6 ms before the window opened. A Bot's reader stamps a
frame only when its task runs, so a stall of the client's event loop longer
than that margin stamps the setup's change inside the window, on one side
only. At a load of 32 to 43 on 4 CPUs, a Python process gets about a tenth
of a CPU, so a stall that long is plausible. At the load measured here, it
did not happen. The failure in #129 was not reproduced at this load, so its
Divergence is still unnamed.

With #181, the builder passes its own barrier before the open Mark. Each of
its two requests first waits for the reader to stamp what reached the socket
(`Connection.caught_up`), and the answers come after the setup's packets on
the same connection. The setup's change is then stamped before the open by
construction, whatever the stall, and the margin grows by the barrier's two
round trips.

## The Reference's 10 s answer timeout under starvation (#134)

The Reference is ready once it answers a status ping, and vanilla answers
one only after it has prepared the level
(`docs/research/2026-09-26-runner.md`), so readiness does not come early.
A Reference console that is silent for 38 s right after startup, at a load
of 35 to 40 on 4 CPUs, is the JVM starved of CPU. A Bot operation's 10 s
bound stays fixed: it is what makes a Candidate that hangs a `mismatch`,
and scaling it with the load would let a hanging Candidate score better.
A Reference timeout on a host loaded far above its CPU count is the host's
fault, not a Verdict.
