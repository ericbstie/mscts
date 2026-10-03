# The status player sample and its cache: 26.3 — 2026-10-03

Evidence behind #32 (`status/with-player`). The question was what vanilla's status
lists for the players online, and when it starts listing a player who has just joined.

Facts are **verified** in this container with `scripts/research/javap.py server <Class>`
(the 26.3 server jar), unless a line says *not shown*.

## The sample (`MinecraftServer.buildPlayerStatus`)

- `hidesOnlinePlayers()` true: `Players(max, online, List.of())`, an empty sample.
- Otherwise the sample holds at most 12 entries: `MAX_STATUS_PLAYER_SAMPLE` is 12 and
  the count is `Math.min(players.size(), 12)` (offsets 39 to 49).
- The entries are consecutive players from the `PlayerList`, starting at a random index
  `Mth.nextInt(random, 0, size - count)` (offsets 60 to 76). So with 12 players or
  fewer, every player is listed.
- Each entry is the player's `nameAndId()`, or `ANONYMOUS_PLAYER_PROFILE` when the
  player does not allow listing (`ServerPlayer.allowsListing`).
- The list is then shuffled with `Util.shuffle(List, RandomSource)` (offset 140), which
  is not `Collections.shuffle`: it walks the list from its size down to 2, drawing an
  index from the server's own `RandomSource.nextInt` at each step (`Util.shuffle`
  offsets 9 to 16).
- With one player online the sample has one entry whatever the shuffle does.

## The cache (`MinecraftServer.tickServer`)

- `status` is rebuilt in `tickServer`, after `tickChildren`, when
  `now - lastServerStatus >= STATUS_EXPIRE_TIME_NANOS` (offsets 123 to 146).
- `STATUS_EXPIRE_TIME_NANOS` is `5 * TimeUtil.NANOSECONDS_PER_SECOND`: 5 s (static
  initialiser, offsets 30 to 37).
- `invalidateStatus()` sets `lastServerStatus = 0`, so the next tick rebuilds. It is
  called at the end of `PlayerList.placeNewPlayer` and when a player is removed
  (docs/research/2026-10-02-settle.md has the offsets). So vanilla lists a player who has
  joined from the tick after the join, not up to 5 s later.
- *Not shown*: how long after its own join a Candidate lists the player. That depends
  on how it caches its status, and `status/with-player` measures it.

## Live

`mscts run --candidate pumpkin --group status/with-player` (2026-10-03, nightly
4426d11): Pumpkin lists the same count and the same name as vanilla, and another UUID
(`status_response.players.sample[].id` and `login_finished.profile.uuid` differ).
The Self-check of the Group matched in 20 plays out of 20.
