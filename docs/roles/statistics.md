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

- #24: statistical tests are in the repo, on the standard library, checked against scipy in a scratch venv and pinned; scipy is no dependency. KS is exact and conditional on ties (the gap checked only at tie-block boundaries); scipy's `method="exact"` is not conditional.
- #24: a statistical Group makes its plays independent: a Bot name rejoins where it left (vanilla saves the player), and entities, time and weather carry over. Use `context.play` for a fresh name.
- #24: test every permutation path on a mid-range p: a case at p = 1 or 1/10,001 lets mutants survive. Test pooling with very unequal row totals.
- #24: a `distribution` Divergence's `reference` and `candidate` hold summaries, not values a server sent.
- #47: a frozen world never freezes players (`TickRateManager.isEntityFrozen`), and their connection tick runs after the level tick: an item is picked up on the step its pickup delay reaches 0, and one with delay 0, or an orb, on the tick its command runs.
- #47: whether two experience orbs merge depends on their entity ids (`(other.id - this.id) % 40 == 0`), and a player takes one orb in reach at random each tick: never compare orb merging, and give each orb its own window.
- #47: items look for merges every 40 ticks of their own age: summon pairs a step apart so each merge lands on its own tick. A pickup that only partly fits sends only `container_set_slot`.
- #47: `/item replace entity <p> container.*` replaces one slot without an error; fill an inventory one slot per command.
