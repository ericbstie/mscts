# Accepting a teleport the server has already replaced (26.3)

Source: javap of the 26.3 server jar (`scripts/research/javap.py server`,
`net.minecraft.server.network.ServerGamePacketListenerImpl`), and the source of Pumpkin
nightly 5b53f06 (`5b53f064af8708ba33fcaa533b81ca29a53a3310`, `Pumpkin-MC/Pumpkin`), for #402.

## What vanilla does with an `accept_teleportation`

- The listener holds one counter, `awaitingTeleport`, and one pending pose,
  `awaitingPositionFromClient`. `teleport(PositionMoveRotation, Set)` (the only place a
  `player_position` is made) adds one to the counter (back to 0 after 2147483647),
  stores the player's position in `awaitingPositionFromClient`, and sends the counter as the
  teleport id (offsets 8 to 31, 39 to 47).
- `handleAcceptTeleportPacket` first compares the packet's id with the counter
  (offsets 12 to 20: `id()`, `getfield awaitingTeleport`, `if_icmpne 180`). If they differ it
  goes to offset 180 and returns. It sends no disconnect and changes nothing.
- Only an id equal to the counter is acted on. Then, if `awaitingPositionFromClient` is null
  (that teleport was accepted already) or the packet's pose has an invalid value
  (`containsInvalidValues`), it disconnects the player with
  `multiplayer.disconnect.invalid_player_movement` (offsets 23 to 66). Otherwise it snaps the
  player to the stored position, clears `awaitingPositionFromClient`, and handles the pose in
  the packet as a move (offsets 67 to 177).
- So an accept of teleport 1 that arrives after the server has sent teleport 2 is ignored, and
  the accept of teleport 2 that follows is the one that counts.

## What Pumpkin does

- The player holds one `awaiting_teleport: Mutex<Option<(VarInt, Vector3<f64>)>>`
  (`crates/pumpkin-core/src/entity/player.rs:465`) and a counter, `teleport_id_count`
  (`player.rs:463`).
- `Player::request_teleport` (`player.rs:4161`) takes the next id (`player.rs:4181-4183`),
  overwrites `awaiting_teleport` with `Some((id, position))` (`player.rs:4189-4193`), and queues
  the `player_position` (`player.rs:4194-4205`). A same-world teleport of a player, such as
  `/tp`, calls it (`player.rs:6859-6870`), and so does the join, in `spawn_java_player`
  (`crates/pumpkin-core/src/world/mod.rs:3310`, after the centre chunk is sent).
- `handle_confirm_teleport` (`crates/pumpkin-core/src/net/java/play/confirm_teleport.rs:5-43`)
  is called inline for each `accept_teleportation`
  (`crates/pumpkin-core/src/net/java/mod.rs:743-749`):
  - `Some((id, position))` with the packet's id: sets the player's position, clears the slot,
    no kick (lines 17-23);
  - `Some` with another id, `WrongId`: kicks with `Wrong teleport id` (lines 24-25, 34-36);
  - `None`, `NotTeleporting`: kicks with `Send Teleport confirm, but we did not teleport`
    (lines 27-29, 37-41).
- So an accept of teleport 1 that arrives after Pumpkin has sent teleport 2 gets the kick. Pumpkin
  keeps no earlier ids to tell a stale accept from a wrong one. An accept that arrives when no
  teleport is pending is kicked as well, whatever its id.

## Where the two differ

- A stale id: vanilla ignores it, Pumpkin kicks.
- An accept with no teleport pending: vanilla ignores it unless its id is the counter's (then it
  disconnects), Pumpkin kicks whatever the id.

## The Bot's order, live (verified, 2026-10-16)

Two probes, kept in the scratch directory
`/tmp/claude-0/-home-user-mscts/69129e96-dcb3-5303-a091-f7710baa105f/scratchpad/B/`
(`teleport_probe.py` and `stale_probe.py`; `run_probe.sh` and `run_stale.sh` run them under the
live lock; the rows are `vanilla.jsonl`, `pumpkin.jsonl`, `stale-vanilla.jsonl` and
`stale-pumpkin.jsonl`). Each boots one Instance at the default ServerSpec and, per play, joins a new
Bot, then has Control run `tp <bot> 0.5 -60 0.5` as soon as `bot.join()` returns, as `_arena` and
`join_at_spawn` do. Pumpkin is nightly 5b53f06 and vanilla is 26.3.

- **The Bot accepts each teleport with its own id, in order** (`teleport_probe.py`, 25 plays on
  vanilla, 40 on Pumpkin, one Bot after another):
  - in all 65 plays the Bot saw teleport 1, sent accept 1 (0.1 to 14.3 ms after it arrived), saw
    teleport 2, and sent accept 2 (0.06 to 11.8 ms after it arrived), in that order;
  - no play had an accept of an old id, and none had an accept before its teleport;
  - Control's `tp` was sent 3.4 to 343 ms after accept 1 on vanilla and 0.6 to 345 ms after it on
    Pumpkin.
- **Pumpkin kicks some of these plays** (4 of 40: plays 2, 14, 19 and 23). The disconnect text is
  `Wrong teleport id`, and it reached the Bot 50 to 70 ms after accept 2. The Bot's packets in
  those plays are the same as in the 36 that were not kicked.
  - The four kicked plays are those where Pumpkin ran the `tp` at once: teleport 2 reached the Bot
    2.8 to 4.7 ms after Control sent it, and Control sent it 0.6 to 1.2 ms after accept 1. Of the
    36 plays that were not kicked, 35 took 41.7 ms or more (the `tp` ran a tick later), and one
    took 18.1 ms. Vanilla took 1.0 to 28.5 ms and kicked none.
  - So Pumpkin set `awaiting_teleport` to 2 before it handled accept 1. The Bot sent accept 1
    before the `tp`, but the two travel on two connections, and Pumpkin runs a `chat_command` in a
    task of its own (#17), so the server can handle them in the other order.
- **A stale accept on purpose** (`stale_probe.py`, 20 plays on each): the script drops the Bot's
  accept of teleport 2, and then sends `accept_teleportation` with id 1.
  - Vanilla: 20 of 20 plays not kicked.
  - Pumpkin: 20 of 20 kicked with `Wrong teleport id`. In 4 of them (plays 1, 10, 11 and 17) the
    kick came before the script sent its own accept 1. The only accept the Bot had sent was the
    join's accept 1, so Pumpkin judged that one against teleport 2: the race above, caught
    without a stale accept of ours.
- The `tp` in the first probe is the same command the Groups send. This note does not check the
  other Groups that `tp` a Bot after its join one by one.
