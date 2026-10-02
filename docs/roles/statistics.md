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
