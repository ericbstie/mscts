# Groups

These are the Groups mscts ships. Each id's first segment is its
mechanic, which the Report uses as a heading. Pass ids or globs to
`mscts run --group`.

## Server list ping (`status`)

What the vanilla client does to fill in a server list entry: a status
handshake, a `status_request`, and then a `ping_request` whose
`pong_response` gives the latency it shows.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `status/basic` | exact | none | Asks for the status once. | none |
| `status/ping` | exact | none | Asks for the status, then pings with a fixed payload. | `status.rtt` |
| `status/with-player` | exact | none | Joins one player, then asks for the status, to compare the online count and the player sample. | none |

`status/ping` sends the fixed Long `20260926` as its ping payload. The
vanilla client sends its clock, but a Group must send the same bytes
every run.

`status/with-player` waits 6 seconds after the join before it asks.
Vanilla drops its cached status when a player joins and lists the player
from the next tick. The wait leaves a margin for a server that caches its
status lazily: it lasts as long as vanilla keeps a status, 5 seconds, plus
one second. A server whose status still lacks the player after the wait shows
no player, and the Report shows that as a difference. Each play of the
Group takes about 14 seconds, so a default Run of five repetitions took
about 70 seconds longer in the stored example (26 s without it, 97 s with
it).

No status Group has a Mask. Nothing in a status exchange is an identifier
without gameplay meaning, so every difference in it is a Divergence.

## Blocks (`blocks`)

What `/setblock`, `/fill` and `/clone` do to the world. A Bot called `builder`, which is an
operator, runs each command itself, in a window of its own. Each Group compares the blocks the
command changes, the data of the block entities, the break particles, the items a block drops,
and the message the server answers the builder with.

The world is frozen and random ticks are off while a Group runs, so nothing changes a block but
the command. Both settings are put back afterwards, and so are the blocks. Every block a Group
changes is in the chunk that holds x and z from 0 to 15, which the builder is sent when it joins.

Vanilla puts a player who joins at a random place near the world spawn, so the builder could
stand where a command sets a block. It would then crawl and take damage, and the server would
tell it so. To keep that out of the comparison, the Group moves the builder with `/tp` to x 0.5, y -60,
z 14.5 before the first window, away from every block a Group changes. The blocks Groups
therefore require `/tp`, and a server without it fails all three.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `blocks/setblock` | exact | none | Runs `/setblock` in each mode (`destroy`, `keep`, `replace`, `strict`), on air and on a block. Then it sets a block with states, a sign with text, a chest with an item, and the block that is already there. Last, it reads the chest back with `/data get block`. | none |
| `blocks/fill` | exact | none | Runs `/fill` over a region of 5 by 5 by 5 blocks that crosses a chunk section border, with blocks already in it: with no mode, with each mode (`destroy`, `hollow`, `keep`, `outline`, `replace`, `strict`), and with `replace` and a block to replace. | none |
| `blocks/clone` | exact | none | Runs `/clone` on a box of 3 by 3 by 3 blocks that holds stone, dirt, a sign with text, a stair, a chest with an item and air: with each of `replace`, `masked` and `filtered`, combined with each of `normal`, `force` and `move`. Then it clones the box onto a box that overlaps it, with `normal`, `force` and `move`. Last, it reads the copied chest back with `/data get block`, after a `normal` and a `move` clone. | none |

The item a block drops in `destroy` mode starts at a random place and speed. `blocks/setblock` and
`blocks/fill` leave out where the item appears (`x`, `y` and `z` in `add_entity`), its sideways
speed (`velocity.x` and `velocity.z`) and which way it faces (`yaw`). Which item drops, and how
many, is still compared. `/clone` drops nothing, so `blocks/clone` has no such Mask.

The server does not send a chest's items to a player who is only watching it, so a window cannot
see them in the block packets. The builder reads them with `/data get block`, and the message it
gets back is compared.

The `/fill` region holds one block that drops an item. Vanilla sends the items a tick drops in an
order that follows their entity ids, and two servers can number their entities differently, so with
several items the Reference would not match itself.

## Chat (`chat`)

What players see of each other's chat. A Bot called `listener` stays in the world for every
case, and each case has a window of its own. The Group compares the chat messages each Bot
receives, the reason a Bot is kicked, and the changes to the player list.

The Bots speak as the vanilla client does when it has no chat signing keys, as an offline
player has none. They send their messages unsigned. A command with a message argument (`/me`,
`/say`, `/msg`, `/teammsg`) is sent the way the client sends it, as a signed command with no
signatures, and vanilla then sends `player_chat` for it. The same command sent unsigned would
get `disguised_chat`. A server that sends `disguised_chat` where vanilla sends `player_chat`
still has every case compared: the window waits for either one, and the Report shows the
difference. A command's window also ends on a `system_chat`, for a server that sends the
command's message as a system message.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `chat/player` | exact | none | A Bot says a plain message, then a message with a link, and the listener receives each. | none |
| `chat/commands` | exact | none | A Bot that is an operator runs `/me`, `/say`, `/msg listener ...`, `/tellraw @a` with gold bold text, and `/teammsg`, on a team with the listener. The team is removed afterwards. | none |
| `chat/join-leave` | exact | none | A Bot joins, then leaves, while the listener is in the world. | none |
| `chat/limits` | exact | none | A Bot says a message of 256 characters, the longest vanilla takes. An operator sends 15 messages at once. Then a Bot says a message of 257 characters, a Bot says a message with a `§`, and a Bot that is not an operator sends 15 messages at once, and each of these three is kicked. | none |

Vanilla takes a message's time from its own clock, since the Bot has no keys to sign the time it
sends. So no chat Group compares `timestamp` in `player_chat`; the message itself is still
compared.

Vanilla kicks a player who is not an operator for spam when the messages it sends add up too
fast: each message counts 20, each tick takes 1 away, and the kick comes at 200. Ten messages
are enough only if no tick falls while they arrive. So the Bot sends 15, all in one write, and
vanilla kicks it whichever message the ticks fall between. Which message is the kick can still
differ between runs, so that case compares only the kick, the message that the Bot left, and the
player list, not the chat before the kick. Freezing the world would not help, because the count
goes down on every tick even then.

The kicks are the last cases, so a server that never kicks makes the Bot wait out its timeout
only after the rest are compared.

## Joining a world (`join`)

What a player receives when it joins, up to the end of the first chunk batch: the login, the configuration (registries, tags and enabled features) and the first play packets (the world, difficulty, abilities, position, inventory, health, experience, recipes, advancements, the world border and the first chunks).

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `join/basic` | exact | none | One player joins alone and receives the first chunk batch. The player spawns exactly at the world spawn (`gamerule respawn_radius 0`), the check that repeats its first position is off (`gamerule player_movement_check false`), and so is natural regeneration (`gamerule natural_health_regeneration false`), which in peaceful raises the player's saturation for as long as it stays online. Once the player has left, the rules are set back to vanilla's defaults, not to the values the server had before. | `join.to_first_chunk` |

The comparison ends when the first chunk batch is complete. Later batches, and the animals that walk into view, depend on timing.

## Multiplayer (`players`)

What a player sees of another player: their entry in the tab list, their body and the chat
messages when they join and leave. A player called `ada` is in the world first, and `bob`
joins, changes game mode or leaves next to her. Each window compares the tab list updates
(`player_info_update`, `player_info_remove`), the other player's body appearing, changing and
going away (`add_entity`, `set_entity_data`, `remove_entities`), and the server's chat messages
(`system_chat`), for both players.

Both players join at the world spawn (`gamerule respawn_radius 0`), with the check that repeats
a joining player's first position off (`gamerule player_movement_check false`), and the world
is frozen (`/tick freeze`). Once a Group is over, the rules are set back to vanilla's defaults
and the world is unfrozen.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `players/join-seen` | exact | none | `bob` joins next to `ada`. Both are compared: what `ada` sees of `bob`, and what `bob` sees of `ada` as he joins. | none |
| `players/leave-seen` | exact | none | `bob` leaves, and `ada` sees him go. | none |
| `players/mode-seen` | exact | none | `/gamemode` sets `bob`'s game mode to creative, adventure, spectator and survival in turn, each in a window of its own. | none |
| `players/server-full` | exact | none | The server lets in one player. `ada` joins, then `bob` tries to join and is refused. The refusal message is compared. | none |

The tab list shows each player's latency, so it is compared. Vanilla sends 0 until it first
measures a player's latency, 15 seconds after they join, so `bob`'s latency in
`players/join-seen` is 0. About every 30 seconds, vanilla also sends every player's latency on
its own. That update is never compared, because it comes at a different time on each server.

Offline, a server makes each player's UUID from their name. A server that makes it another way
shows the other player with another UUID, in the tab list and in their body.

## Movement (`movement`)

What the server does with the moves a player's client reports. The server checks each move
against where it has the player: a move too far for one tick, a move into a block, a player
floating in the air for too long. When it refuses a move, it sends the player back
(`player_position`). When it refuses the player, it kicks them (`disconnect`). The Groups compare
only these two packets.

A Bot does not simulate physics: each Group gives every position the Bot reports. Control moves
the Bot to where each case starts with `/tp`. The Bots join with vanilla's speed check off
(`gamerule player_movement_check false`), and it is turned on again as soon as they have joined.
During a join, that check can send a player back to where it already is, which would change the
teleport number of every later teleport.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `movement/too-fast` | exact | none | A Bot moves 1, 5, 9, 11 and 20 blocks, each in one move. Then it sends two moves of 8 blocks in one tick, and six moves of 2 blocks in one tick. | none |
| `movement/into-blocks` | tick-exact | none | A Bot walks into a wall, through a gap 1 block wide and 2 high, up onto a full block without jumping, and up onto a slab. The world steps one tick after each move. | none |
| `movement/flying` | exact | none | Three Bots rise 1.5 blocks into the air. A creative Bot stays there. A survival Bot lands again after about 15 ticks, well before vanilla's limit of 80, and must not be kicked. Another survival Bot stays there until the server kicks it. The creative Bot rises first, so by then it has floated at least as long. | none |
| `movement/before-teleport` | tick-exact | none | A Bot walks into a wall, then sends three more moves before it accepts the teleport the server answers with. | none |

Vanilla checks a move's speed only while the world runs normally, not while it is frozen. So
`movement/too-fast` runs in a running world. `movement/flying` also runs in a running world.
Freezing it would not change when vanilla kicks, because vanilla counts the ticks a player floats
either way. In `movement/into-blocks` and `movement/before-teleport`, vanilla checks speed again
for the packets it reads just after each step. None of their moves arrives then, and none is
long enough to be refused.

`movement/flying` compares the kick's message, not when it comes. A server that kicks a player
after fewer than about 15 ticks in the air kicks the Bot that lands, and differs. A server that
kicks later than vanilla, but within 10 seconds, does not differ.

The moves of one tick are sent back to back, and the server must take them in one tick. Vanilla
reads what has arrived at the start of each tick, so if a tick starts while the moves are still
arriving, the server takes them in two ticks and refuses none. This is rare. Each window opens by
waiting for the server's answer to a request, which it sends at the start of a tick. The moves go
out just after it, so they arrive about 50 ms before the server next reads. They are also sent
within a millisecond.
## Chunk loading (`chunks`)

Which chunks the server sends a player, which chunks it tells the player to unload, and where
it centres the player's view. A player called `walker` joins alone at the world spawn
(`gamerule respawn_radius 0`), with the world frozen (`/tick freeze`). Each comparison lasts
until the walker has every chunk of its view, as vanilla works the view out, and about 9 ticks
more. A server that never sends one of them fails the Group after 10 seconds. A chunk sent, or
unloaded, in those 9 ticks is compared. One sent later is not.

The chunks Groups require no other Group. A join that fails fails the Group, but a join whose
packets differ from vanilla's, which `join/basic` reports, still has its chunks compared. The
login and configuration packets are compared in every Group, so each chunks Group also lists
the join's differences, such as in `registry_data` or `update_tags`.

The view distance is the ServerSpec's unless the Group says otherwise. Every chunks Group sets
its own: 2, or 5 for `chunks/view-distance`.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `chunks/join-view` | exact | none | The walker joins and is sent the chunks around it: the 7 by 7 chunks around its own at view distance 2. | none |
| `chunks/view-distance` | exact | none | The same as `chunks/join-view`, with view distance 5. | none |
| `chunks/teleport` | exact | none | Once the walker has its view, Control teleports it 20 chunks east. The walker is told to unload its old chunks and is sent the chunks around its new position. | none |
| `chunks/walk` | exact | none | Once the walker has its view, it walks west into the next chunk, one step a tick. The walker is told to unload the column of chunks it left behind and is sent the column ahead. | none |

The chunks are compared by position and content. Their order is not compared, and neither is
which chunk batch carries each chunk: two vanilla servers split the same chunks into batches
differently, depending on how soon each chunk is ready. A chunk that comes before another
packet on one server and after it on the other, such as the player's position, is a difference
only when it changes the order of the chunks around that packet, because the client applies
them in turn.

When a Group ends, the walker is moved back to the world spawn, because the server keeps where
a player left and its next join starts there. Then the world is unfrozen and the rules are set
back to vanilla's defaults.

## Planned

| Mechanic | First Group | Needs |
| --- | --- | --- |
| Redstone and glitches | Tick-by-tick observation under `/tick freeze` and `/tick step` | Its Groups. The `tick-exact` kind they use exists. |
| Spawning and loot | Distributions over many runs | The `statistical` kind, in its own opt-in tier. |
| Invalid moves | `movement/invalid`: a coordinate that is not a number, an infinite one, and a pitch of 91 | A Bot that can send a move as given. Today a Bot refuses such a coordinate, and holds pitch between -90 and 90 as the vanilla client does. |

See [Project status](/status) for the order.

## How chunks are compared

mscts compares a chunk the way the vanilla client ends up seeing it:
the block at each position, the biome of each 4×4×4 cell, the
heightmaps, the block entities, and the sky and block light of each
section. Two servers can encode the same chunk in different ways; that
is reported as a network traffic difference. A different block or light
level is reported per chunk section, with the positions that differ.

## Built-in Measurements

| Name | Unit | Source |
| --- | --- | --- |
| `status.rtt` | ms | The `status.rtt` span in `status/ping`: from sending the ping to receiving the pong. |
| `join.to_first_chunk` | ms | The `join.to_first_chunk` span in `join/basic`: from the start of the login to the end of the first chunk batch. |
| `instance.startup` | ms | Every Run: from launching a server until it is ready. |
