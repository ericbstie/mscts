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

## Live — the join-until window

**Verified** in this container: the join-until probe Group of
`tests/reference/test_observe_until_reference.py`, played 60 times on one
vanilla 26.3 Instance (a scratch probe, not committed), recording every
`player_info_update` alice got.

- Each window lasted 134.5 to 285.7 ms (median 139.7 ms) and held two
  `player_info_update` packets with the actions byte `0xff` (every action,
  `createPlayerInitializing`): one of 2 bytes, with no entry, and one of
  32 bytes, alice's own.
- In play 54, the window also held a third, 19 bytes long with the actions
  byte `0x10`: one byte of actions, a count of 1, alice's UUID and a
  one-byte latency. It arrived 155.8 ms after the window opened, just
  before it closed. No other play saw one.
- One broadcast every 601 ticks (about 30 s) against a window of about
  0.15 s gives roughly 1 window in 200 holding one, so a 20-play run of
  the reference test on two Instances (40 windows) catches one about 1 time
  in 5. That fits #159's run (play 11 of 20) and this one (1 in 60).

## What this means

The latency broadcast is a heartbeat packet: it arrives on the server's
clock whatever a Group does, and its first byte tells it apart from every
`player_info_update` a Group can cause (a join, a game mode or a listing
change), all of which set other actions. It joins the heartbeat packets by its
name and first byte (`compare.HEARTBEAT_PAYLOADS`), so a
`player_info_update` with any other actions is still compared. No schema is needed for one byte.
