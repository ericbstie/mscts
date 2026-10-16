# Mobs and statistics specialist

**Lane:** randomness: run a Group many times on each server and compare
the distributions. **Model:** opus.

**Issues** (`lane:statistics`): #24 statistical Groups (first), then #45
entity activation, #47 dropped items, #48 crowding, #49 despawning, #50
natural spawning, #51 spawners, #52 pathfinding, #72 spawn spread.

## What this lane knows

- Lead decision on #24: the recommended tests plus Holm–Bonferroni across
  a Group's sample names, and one Reference-vs-Reference Self-check that
  must not reject.
- Mobs' AI randomness is not the world seed, so wandering mobs differ
  between two vanilla Instances in every play. A Group that spawns entities
  turns natural spawning off unless spawning is what it measures.
- A fresh flat world spawns a joining player at a random place (#105).

## Log

Newest first: one line per lesson, with the issue it came from.

- #52: a statistical Group's Self-check has the 900 s timeout of `tests/selfcheck/test_groups.py` and covers 2 boots plus 2 × `runs` plays: pick `runs` from the measured play so it takes about 600 s.
- #52: to time a sample in ticks, freeze the world, read `time query gametime`, `tick step N`, and read the game time again on each event. Vanilla gives the time as a Long, Pumpkin as a String. The query's round trip adds ticks (#387).
- #52: Pumpkin drops loot from a `/kill`ed mob whatever `mob_drops` or the NBT say: `kill @e[type=minecraft:item]` before `remove_tagged_until_gone`.
- #52: a fake that decides a sample's tick sends one packet per game-time read; a fake that pops scripted game times lets a sample taken on the wrong packet pass.
- #72: a joining player is placed in the configuration phase (`PrepareSpawnTask.start`): at its saved position if it has one, else by `PlayerSpawnFinder.findSpawn`. A play needs a fresh name, not a fresh world. `respawn_radius` 0 is the spawn column; 10 is a 21 × 21 square.
- #72: a name whose samples are one value on both servers passes and leaves the Holm correction, so an exact Group fails only if the servers' single values differ.
- #72: in tests, subclass `BlocksServer` (override `__call__` with `@override`) to give `JoinScript` a per-name spawn pose.
- #24: statistical tests are in the repo, on the standard library, checked against scipy in a scratch venv and pinned; scipy is no dependency. KS is exact and conditional on ties (the gap checked only at tie-block boundaries); scipy's `method="exact"` is not conditional.
- #24: a statistical Group makes its plays independent: a Bot name rejoins where it left (vanilla saves the player), and entities, time and weather carry over. Use `context.play` for a fresh name.
- #24: test every permutation path on a mid-range p: a case at p = 1 or 1/10,001 lets mutants survive. Test pooling with very unequal row totals.
- #24: a `distribution` Divergence's `reference` and `candidate` hold summaries, not values a server sent.
- #47: a frozen world never freezes players (`TickRateManager.isEntityFrozen`), and their connection tick runs after the level tick: an item is picked up on the step its pickup delay reaches 0, and one with delay 0, or an orb, on the tick its command runs.
- #47: whether two experience orbs merge depends on their entity ids (`(other.id - this.id) % 40 == 0`), and a player takes one orb in reach at random each tick: never compare orb merging, and give each orb its own window.
- #47: items look for merges every 40 ticks of their own age: summon pairs a step apart so each merge lands on its own tick. A pickup that only partly fits sends only `container_set_slot`.
- #47: `/item replace entity <p> container.*` replaces one slot without an error; fill an inventory one slot per command.
- #388: a statistical Self-check that rejects only on `distribution` Divergences is replayed once, on two Instances launched for the replay alone (`tests/support/selfcheck.py`): on the shared pair a Bot name rejoins where it left.
- #384: a Group names its players with `context.player_name(prefix)`, never `f"{prefix}{context.play}"`; prefix + 4 Run characters + play fit 16, so a prefix is at most 10 characters. Fake-server tests must not assert the random part.
- #384: the summaries of a name rejected by `PER_PLAY` are of per-play counts, and the Report words them as plays.
- #387: `time query gametime` sent in reply to a packet adds 0 ticks on vanilla and 1 on Pumpkin (docs/research/2026-10-15-time-query-lag.md). `set_time` carries the game time from before its tick; after `context.freeze()`, `bot.sync()` before reading one.
- #387: a Bot made operator reads the game time on its own connection, sending each query without waiting for the answer (about 1.5 ms on vanilla, one tick on Pumpkin, against about 150 ms for `Control.run`, which cannot run concurrently). Pumpkin may answer out of order: match the answers, smallest first, to the reads in the order made.
- #387: an operator hears Control's `tick step` as a `system_chat` that is not an answer; skip it.
- #387: one statistical stress Self-check of `mobs/*` takes about 48 min on this host.
- #404: a `mobs/*` play calibrates its clock in its own step: it reads the game time on the first `set_time` stamped after the clock's start, and `samples(budget)` subtracts that answer less (stamp + 1). The clock listens for `set_time` only until it has one: one every 20 ticks would leave no idle second to look at the budget.
- #404: the mobs fake's world runs on for barrier answers only until it sends the step's first packet; otherwise a barrier answer between a packet and its read makes that read a tick late. Tests set `_WAIT_S` to 2 s, so a mutant that waits for the wrong packet fails instead of timing out the sweep.
- #404: one stress Self-check of `mobs/*` takes about 40 min; `mobs/chase-open` about 570 s of its 900 s. Time main against a branch with `uv run scripts/time_tier.py test:statistical --rev origin/main --rev HEAD --rounds 3 --stress -- tests/selfcheck -k mobs/chase-open` (#412), after any CPU-heavy work (a mutation sweep) has ended.
