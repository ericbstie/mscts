# ADR-0013: The Fixture world has natural mob spawning off

Status: accepted (2026-10-03)

## Context

A mob near the spawn plays its sounds at random, and vanilla sends them to
every player within 16 blocks, even before the player has any chunks. In the
join probe of #183, pigs spawned near the spawn after a few minutes, and a
sound landed in one Instance's join window only
(`docs/research/2026-10-03-join-sounds.md`). Any Group near the spawn could
differ between two runs the same way. #183 first cleared the mobs inside
that one Group. The maintainer chose to turn spawning off for every Group
instead (#200, option B).

## Decision

- Every Instance starts with the game rule `spawn_mobs` false, from the
  first tick. It is an invariant like offline mode, not a ServerSpec field.
- Vanilla 26.3 and Pumpkin read their game rules from
  `world/data/minecraft/game_rules.dat`, not from their config. Every
  Adapter writes that file (ADR-0007's native files).
  `adapters/fixture_world.py` builds it: only `minecraft:spawn_mobs`, every
  other rule left to its default, stamped with the server's DataVersion.
- A server that reads its game rules from somewhere else is out of scope
  until an Adapter needs one.
- A Group that tests natural spawning turns the rule on itself with
  Control, and off again when it is done.

## Consequences

- No Group has to clear mobs before a window near the spawn.
- A unit test prepares every Adapter in `ADAPTERS` and fails if the file
  is missing or leaves `spawn_mobs` on. Both servers fall back to their
  defaults, spawning on, without failing, if they cannot read the file. So
  the reference and candidate tiers each ask a running server for
  `spawn_mobs` and expect `false`.
- The rule stops natural spawning on both servers. Mobs that a new chunk
  generates with are different. Pumpkin skips them when the rule is off,
  but vanilla does not check the rule for them. Vanilla's flat world
  generates no mobs, so the Fixture has none. A WorldPreset other than
  flat would generate animals on vanilla but not on Pumpkin.
