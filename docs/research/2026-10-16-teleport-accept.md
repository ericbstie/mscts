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
