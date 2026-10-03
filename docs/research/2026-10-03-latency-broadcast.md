# The latency broadcast: a heartbeat `player_info_update` — 2026-10-03

Evidence behind #165: a join-until window (`observe(until=
"minecraft:chunk_batch_finished")`) on one of two vanilla Instances held a
`player_info_update` that the other's did not (play 11 of 20, seen in
#159's reference tier run). Bytecode was read with
`scripts/research/javap.py` from the 26.3 server jar.

## Who sends `UPDATE_LATENCY` alone — javap

- `PlayerList.tick` increments `sendAllPlayerInfoIn`; when it passes
  `SEND_PLAYER_INFO_INTERVAL` (600), it calls `broadcastAll(new
  ClientboundPlayerInfoUpdatePacket(EnumSet.of(UPDATE_LATENCY), players))`
  and sets the counter back to 0. So every 601 ticks, every player gets one
  entry for each online player, with that player's latency. The counter
  belongs to the server, not to a player: when it fires relative to a
  join is timing.
- `UPDATE_LATENCY` appears in only three classes of the server jar
  (`grep` over the extracted classes): `PlayerList`,
  `ClientboundPlayerInfoUpdatePacket` and its `Action` enum. The packet
  class uses it only in `createPlayerInitializing`, which sends it
  together with `ADD_PLAYER` and five other actions. So a
  `player_info_update` whose only action is `UPDATE_LATENCY` comes from
  `PlayerList.tick` and nothing else.
- The actions go first on the wire, as a fixed bit set
  (`FriendlyByteBuf.writeEnumSet` → `writeFixedBitSet(bits, 8)`): one
  byte, bit *n* for the action of ordinal *n*. `Action` has 8 values:
  `ADD_PLAYER` 0, `INITIALIZE_CHAT` 1, `UPDATE_GAME_MODE` 2,
  `UPDATE_LISTED` 3, `UPDATE_LATENCY` 4, `UPDATE_DISPLAY_NAME` 5,
  `UPDATE_LIST_ORDER` 6, `UPDATE_HAT` 7. So the latency broadcast starts
  with the byte `0x10`, and no other set of actions does. Then come a
  VarInt count and, per entry, a UUID and a VarInt latency.
- The 2026-09-30 note (`2026-09-30-observation-window.md`, What arrives
  on a clock) measured it live: about every 30 s, the world frozen too,
  on vanilla only. Pumpkin sent none.

## What this means

The latency broadcast is a heartbeat packet: it arrives on the server's
clock whatever a Group does, and its first byte tells it apart from every
`player_info_update` a Group can cause (a join, a game mode or a listing
change), all of which set other actions. It can join the heartbeat packets by its
name and first byte, so a `player_info_update` with any other actions is
still compared. No schema is needed for one byte.
