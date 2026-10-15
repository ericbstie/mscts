# Where a new player first appears (26.3)

Source: javap of the 26.3 server jar (`scripts/research/javap.py server -v`), for #72.

## Which code places a joining player

- The player is placed in the configuration phase, by
  `PrepareSpawnTask.start`, before `PlayerList.placeNewPlayer` runs.
  `placeNewPlayer` does not place it.
- `start` calls `PlayerList.loadPlayerData(nameAndId)`. If the saved data holds a
  position, the player goes there (`ServerPlayer$SavedPosition`).
  Only when it holds none does `start` call
  `PlayerSpawnFinder.findSpawn(level, respawnData.pos())`.
- The saved data is the player's file, keyed by its id (offline mode: the
  UUID made from the name). A name that has not joined before has none,
  so a play needs a fresh player name, not a fresh world.
- `ServerPlayer.adjustSpawnLocation` calls the same `findSpawn`. A
  new player does not take that path.

## What the finder does

- A world whose game type is `ADVENTURE` gets no spread: `fixupSpawnHeight`
  on the spawn.
- Else `radius = max(0, respawn_radius)`, cut to the player's distance to
  the world border (and 1 if that is 1 or less).
- It tries `min(1024, (2 * radius + 1)^2)` candidates. A random start
  (`RandomSource.createThreadLocalInstance().nextInt(count)`) and a step
  coprime with the count visit each once. Candidate `value` is the block
  `(spawn.x + value % side - radius, spawn.z + value / side - radius)`.
  The first safe one wins. If none is, the spawn column itself.
- So `respawn_radius 0` gives one candidate, the spawn column. The default
  10 gives 441, within 10 blocks of the spawn on both axes.
- The game rule is `respawn_radius` (`GameRules.RESPAWN_RADIUS`), an
  integer, 10 by default.
