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

Vanilla puts a player who joins at a random place near the world spawn, so the builder, or
Control, could stand where a command sets a block. It would then crawl and take damage, and the
server would tell the builder so. To keep that out of the comparison, the Group moves both with
`/tp` before the first window, the builder to x 0.5, y -60, z 14.5 and Control to x 3.5, y -60,
z 14.5, away from every block a Group changes. The blocks Groups therefore require `/tp`, and a
server without it fails all three.

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

### Blocks a player breaks and places

Two Bots, `digger` and `watcher`, join. The digger breaks and places blocks. The watcher stands
beside it, because vanilla does not send the cracks and break particles of a dig to the player who
digs. Control puts the digger, the watcher and itself at x 8.5, 12.5 and 4.5, y -60, z 4.5, with
`/tp`, before the first window, and sets each case up with `/setblock`, `/fill`, `/summon`,
`/item replace entity` (the tool or the stack the digger holds, in its first hotbar slot) and
`/kill`. The world is frozen and random ticks are off. The Groups require all of those commands.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `blocks/dig-survival` | exact | none | In survival, the digger breaks a block one and a half blocks south of it. First it finishes two digs as soon as it has started them, which the server refuses: stone by hand, and obsidian with a diamond pickaxe. Then it finishes digs after the time a vanilla client takes, or a second past the least the server accepts, which break the block: stone with a wooden pickaxe, stone with an iron pickaxe, dirt by hand, stone by hand and obsidian with a diamond pickaxe. Last it finishes the first two digs early again, and the server breaks each block a tick later. Each dig is two windows: the start, then the finish. | none |
| `blocks/dig-creative` | tick-exact | none | In creative mode, the digger breaks stone, dirt and obsidian by hand, each in one window, then tries stone with an iron sword, which cannot break blocks. | none |
| `blocks/place` | tick-exact | none | The digger places stairs and logs on each of the six faces of a stone block, stairs while facing each of four ways, and a slab (bottom, top and doubled). | none |
| `blocks/place-attached` | tick-exact | none | The digger places a door with the cursor on each side of the block, a torch (on top and on each side), and a bed facing each of four ways. Then it places stone onto short grass and onto a snow layer, which it replaces, and into the space of an armor stand, which the server refuses. | none |

A dropped item has the same Masks as in the commands above: where it appears, its sideways speed and
which way it faces.

`blocks/dig-survival` cannot be tick-exact. The server counts a dig in the player's own ticks, and
a frozen world still ticks its players, so stepping the world does not time a dig. The Group waits
by the clock instead, outside any window. It compares what the finish changes: the block, the
acknowledgement, the item that drops and the tool's wear. It leaves out the cracks and particles of
the dig (`block_destruction`, and the `level_event` 2019 and 2020 that vanilla sends every tick),
because how many a window holds depends on how long it lasts. That also leaves out `level_event`
2001, the particles and sound of a block that breaks, which `blocks/dig-creative` compares.

The server breaks the block at the finish when the ticks since the start, times the block's
progress in a tick, reach 0.7. When they do not, it keeps the dig, and on the player's next tick it
breaks the block anyway if the player's age in ticks at the start, times that progress, reaches 1.
The age counts from the player's join or its last respawn. So an early finish from a player that
has just joined is refused for good, and one from a player that has been in the world long enough
breaks the block a tick later: 149 ticks (about 7.5 seconds) for stone by hand, and 187 for obsidian
with a diamond pickaxe. The Group plays both. Its first early finishes come right after the digger
joins, and the last ones after the on-time finishes, which keep it in the world for more than 21
seconds.

Each on-time finish waits at least a second past the least the server accepts, so that a server
that runs late still accepts it. The other three digs have no early finish that the server refuses
for good: it breaks them a tick later from a player that has been in the world for 22 ticks
(stone with a wooden pickaxe), 14 (dirt by hand) or 7 (stone with an iron pickaxe), and the digger
is older than that before its first window.

### Falling blocks and blocks that lose their support

A Bot called `watcher` joins at the world spawn, and Control stands 6 chunks away. The world is
frozen and random ticks are off. Control builds every case with `/setblock` first, and steps the
world 5 ticks, so that the ticks the blocks schedule when they are placed have run. Each window
then removes one block with `/setblock ... air` and steps the world a fixed number of ticks, one
at a time, until nothing moves. Each window compares, tick by tick, the blocks, the falling block
as it appears, lands and goes, the items that drop, the break particles, and the sounds
and world events. When a Group ends, Control clears its blocks and kills the items they dropped. The Groups
require `/tp`, `/setblock`, `/fill`, `/kill`, `/gamerule` and `/tick`.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `blocks/gravity` | tick-exact | none | Removes the block under a column of sand, gravel and red sand 6 high (18 ticks), under white concrete powder that falls into water (8 ticks), and under an anvil (8 ticks). Then it removes the block under sand that falls onto a torch (11 ticks) and onto a bottom slab (10 ticks), which each break it into an item. | none |
| `blocks/support` | tick-exact | none | Removes the block under a torch, a rail, a lever, a poppy, a door and a bed, and the block behind a wall torch and a ladder, and steps 1 tick each time. | none |

The anvil falls one block. Vanilla chips an anvil that falls further at random: half the time
after a fall of 10 blocks.

`blocks/gravity` does not compare how a falling block moves. Vanilla sends that every few
ticks, counting the ticks in which the world is frozen, so the tick it comes in depends on how
long each step takes.

The item a falling block breaks into appears where the block was. Its sideways speed and which
way it faces are random, so `blocks/gravity` leaves them out. Where it appears, which item it is
and how many are still compared. The item moves at random from the next tick, so its window ends
on the tick it appears, and Control kills it before the next window.

In vanilla, a block that loses its support breaks at once, in the command that removes the
support, and the tick after brings nothing more. A bed needs nothing under it, so it stays. The
item a block drops has the same Masks as in the commands above: where it appears, its sideways
speed and which way it faces. `blocks/support` does not compare how the item moves, and Control
kills it before the next window.

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
| `chat/limits` | exact | none | A Bot says a message of 256 characters, the longest vanilla takes. An operator sends 15 messages at once, and a Bot that is not an operator sends 9. Then a Bot says a message of 257 characters, a Bot says a message with a `§`, and a Bot that is not an operator sends 15 messages at once, and each of these three is kicked. | none |

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

Nine messages at once count 180, so vanilla never kicks for them. That case compares the
messages too. A server that kicks for fewer than 10 messages differs there.

The kicks are the last cases, so a server that never kicks makes the Bot wait out its timeout
only after the rest are compared.

## Joining a world (`join`)

What a player receives when it joins, up to the end of the first chunk batch: the login, the configuration (registries, tags and enabled features) and the first play packets (the world, difficulty, abilities, position, inventory, health, experience, recipes, advancements, the world border and the first chunks).

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `join/basic` | exact | none | One player joins alone and receives the first chunk batch. The player spawns exactly at the world spawn (`gamerule respawn_radius 0`), the check that repeats its first position is off (`gamerule player_movement_check false`), and so is natural regeneration (`gamerule natural_health_regeneration false`), which in peaceful raises the player's saturation for as long as it stays online. Before the player joins, the weather cycle is stopped (`gamerule advance_weather false`) and the weather cleared, and the Group lets the world run the 100 ticks a storm takes to fade, because a storm one server started would reach the player on that server only. Once the player has left, the rules are set back to vanilla's defaults, not to the values the server had before. | `join.to_first_chunk` |

The comparison ends when the first chunk batch is complete. Later batches, and the animals that walk into view, depend on timing.

The recipes in the recipe book are numbered again, as in the [crafting Groups](#crafting-crafting).

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
floating in the air for too long, a move with values no client sends. When it refuses a move, it sends the player back
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
| `movement/invalid` | exact | none | Three Bots each send a move that no vanilla client sends. One sends an infinite x, then a y of minus infinity. Vanilla sends the Bot back each time, because the move is too long. Another Bot sends an x that is not a number, and the last one an infinite pitch. Vanilla kicks each of them. | none |

Vanilla checks a move's speed only while the world runs normally, not while it is frozen. So
`movement/too-fast` and `movement/invalid` run in a running world. `movement/flying` also runs
in a running world.
Freezing it would not change when vanilla kicks, because vanilla counts the ticks a player floats
either way. In `movement/into-blocks` and `movement/before-teleport`, vanilla checks speed again
for the packets it reads just after each step. None of their moves arrives then, and none is
long enough to be refused.

`movement/flying` compares the kick's message, not when it comes. A server that kicks a player
after fewer than about 15 ticks in the air kicks the Bot that lands, and differs. A server that
kicks later than vanilla, but within 10 seconds, does not differ.

In `movement/invalid`, a server that does not kick a Bot within 10 seconds fails the Group. So
does a server that kicks the Bot sending the infinite coordinates. The two moves that vanilla
kicks for are then never sent, but the Report still lists their kicks as missing.

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

## Combat (`combat`)

What the server does when one player or mob hits another: the damage, the knockback, and the
sounds. A Bot called `fighter` hits a husk that cannot think (`NoAI`) and does not speak
(`Silent`) with the item in its hand. A husk has a zombie's health and knockback but does not
burn in daylight, which a zombie does at random. The server runs on normal difficulty, because
peaceful removes a hostile mob. In the Groups with a fighter, the fighter is an operator.

The world is frozen (`/tick freeze`) and Control steps it, so a husk stands where it is put
and moves only when a Group steps. A window compares the damage (`damage_event`), the husk's
health (`set_entity_data`), its velocity (`set_entity_motion`), the sounds and the particles, and
the swing of the arm that hit (`swing_animation`). It leaves out the husk's position packets:
vanilla resends the position of a husk that stands still about every 3 seconds, so one lands in
a window now and then.

A swing goes to the players who see the swinger, never to the swinger. So the swing is in the
windows of `combat/immunity`, `combat/pvp` and `combat/pvp-off`, where a second Bot watches,
and not in the windows with a fighter alone.

A window of its own follows each hit. In it the fighter copies the `Health`, `Motion` and `Pos` of
each husk to command storage (`data modify storage`) and reads them back (`data get storage`), and
the answers are compared. The answer to `data get entity` would name the husk with its UUID, which
differs between servers. A frozen husk keeps all three values until the world steps, so they are
exact. That is how the Groups compare the husk's health, its knockback and how far the hit moved
it where the hit's own window cannot.

A player is never frozen, so a Bot's attack charge counts every server tick, stepped or not.
A hit at part of the charge would depend on how long the Bot took, so every hit in these Groups
comes after 15 steps, which is more than the 20 ticks an axe needs. Hits at part of the charge
are not compared.

A husk's hurt sound has a random pitch, and the sounds a player makes when it hits have a fixed
one, so the husk is silent and the windows compare every pitch they hold. Only `combat/pvp` has
a player's hurt sound in its window, and there the pitch of every sound is left out. The sound
of a hurt husk is not compared.

Each hit is played in a lane of its own, and Control waits at the end until the husks it killed
are gone, so the next play starts without them. The Group fails if a husk is still there after
20 asks.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `combat/melee-mob` | tick-exact | none | The fighter hits a husk with a bare hand, a wooden sword, a diamond sword and a diamond axe, each at full charge. | none |
| `combat/critical` | tick-exact | none | The fighter hits a husk with a diamond sword twice. The first hit comes while the fighter falls: it hops a block into the air and comes down half a block before the hit, which makes it critical. The second comes while the fighter sprints, which is not critical. | none |
| `combat/knockback` | tick-exact | none | The fighter hits a husk with a diamond sword while standing, then while sprinting. A sprinting hit knocks the husk back further, which shows in its velocity and position. | none |
| `combat/sweep` | tick-exact | none | The fighter hits a husk with a diamond sword on the ground, with three more husks 0.9 blocks from it. The sweep hurts all three. | none |
| `combat/immunity` | tick-exact | none | Two Bots, `striker` with a diamond sword and `tapper` with a bare hand, hit one husk a few ticks apart: the striker then the tapper after 5 ticks, the tapper then the striker after 5, and the striker then the tapper after 11. A hurt husk ignores a hit that is not stronger than the last until its immunity is down to 10 ticks. | none |
| `combat/pvp` | tick-exact | none | A Bot called `attacker` hits another Bot, `victim`, with a diamond sword, standing and then sprinting. The window also compares the victim's health (`set_health`). | none |
| `combat/pvp-off` | tick-exact | none | The same two Bots, with the `pvp` game rule off (`/gamerule pvp false`, which Control turns on again afterwards). `attacker` hits `victim` once with a diamond sword, standing. The window compares what the server sends about a hit that does no damage, and the victim's health (`set_health`). | none |

Vanilla sends the data and the velocity of every entity a tick changed at the end of that tick, in
the order of a hash of their entity ids, and the two Instances' ids differ. A sprinting hit changes
the husk's health and the fighter's sprint flag, which the hit clears, so the order of those two
packets differs between runs of vanilla itself. The Comparison does not compare the order of the
resends of different entities in one tick, so the windows of the sprinting hits in
`combat/critical`, `combat/knockback` and `combat/pvp` compare `set_entity_data`: the husk's
health, and whether the fighter's sprint stops. The window of `combat/sweep` compares only the
damage, the sounds and the particles, because the sweep hurts four husks, and the health and
velocity of each husk are read back.

In `combat/knockback` the husk's velocity and position, in the window and in the readback, say how
far a sprinting hit knocks it back.

A Player keeps its health and its food from play to play, so each Bot is given health and
saturation (`effect give`) before the first hit. In `combat/immunity` the tapper stands a block
behind the striker, out of the sweep of the striker's sword. `combat/pvp` runs with player
versus player damage on, which is the server default, and `combat/pvp-off` with it off. The
sprinting hit is not played with it off.

### Damage and armor

How much each kind of damage costs a player, and what the server sends about it. A Bot called
`victim` is hurt by Control's `/damage`, one kind of damage at a time, and each hit has a window of
its own. A window compares the damage (`damage_event`, `hurt_animation`, `entity_event`), the
health (`set_health`, and the health in `set_entity_data`), the push of the hit
(`set_entity_motion`), the stacks the Bot holds (`container_set_slot`, which shows armor wearing
down), the sounds, and a death (`player_combat_kill`, `system_chat`). The server runs on normal
difficulty. `set_equipment` is not compared, because a server sends it to the players who see
the Bot and never to the Bot itself.

A player is immune for 10 ticks after a hit, counted in its own ticks, which run in real time
even in a frozen world. A second hit inside that gap hurts only by the excess and sends no
`damage_event`, so stepping the world does not clear it. The Bot is killed and respawned before
each hit instead, which gives it full health and food and no immunity. Natural regeneration is
off. A server keeps where a player left, so the Bot is put back at the spawn when a Group ends.

`player_attack`, `mob_attack` and `arrow` need someone to deal the damage. Control summons a
marker for it, an entity a server tells no player about, so it adds no packet.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `combat/damage-types` | tick-exact | none | The Bot wears no armor and takes 4 points of `generic`, `player_attack`, `mob_attack`, `arrow`, `fall`, `in_fire`, `lava`, `magic`, `wither`, `explosion`, `out_of_world` and `starve` damage, a window each. | none |
| `combat/armor` | tick-exact | none | The Bot wears iron, diamond and netherite armor, then diamond armor enchanted with Protection IV, Fire Protection IV and Blast Protection IV, and takes damage through each set: the six kinds that armor reduces through every set, and all twelve kinds through the Protection set. | none |
| `combat/effects` | tick-exact | none | The Bot wears no armor, has Resistance I, II, III or IV, or Absorption II. It takes all twelve kinds of damage under Resistance I and Absorption II, and four of them under Resistance II, III and IV. | none |
| `combat/death` | tick-exact | none | The Bot takes 100 points of `generic`, `fall` and `magic` damage with `show_death_messages` on, and of `generic` damage with it off. Each death has a window, and the respawn after it has another, which fails the Group if entity event 60 comes in it before the respawn. | none |

Armor reduces some kinds of damage and not others. In vanilla 26.3, `generic`, `fall`, `magic`,
`wither`, `out_of_world` and `starve` are in the damage type tag `bypasses_armor`, so the
sets change what the other six cost: `player_attack`, `mob_attack`, `arrow`, `in_fire`, `lava`
and `explosion`. A hit that armor reduces wears each piece down by 1, except a piece that resists that damage
(netherite, against `in_fire` and `lava`), and the Bot is told of each wear
(`container_set_slot`). `combat/armor` has the Bot keep its stacks when it dies, so that one
set of armor serves every kind of damage. The stacks are cleared when the Group ends.

Without an enchantment, a set hurts as much as no armor for the six kinds in `bypasses_armor`,
which `combat/damage-types` compares. So iron, diamond, netherite and the Fire Protection and
Blast Protection sets meet the six kinds that armor reduces, and the Protection set meets all
twelve. A play of a Group has to fit in the Self-check's time, and every window costs a kill and
a respawn.

A kill clears a player's effects, so `combat/effects` gives the Bot its effect again after each
respawn, before the window. Resistance II, III and IV meet `generic`, `arrow`, `out_of_world` and
`starve`, an ordinary hit, one an attacker deals and the two that bypass Resistance, for the same
reason as in `combat/armor`. In vanilla 26.3, Resistance cuts a hit by 20% a level, except for
`out_of_world` (the tag `bypasses_resistance`) and `starve` (`bypasses_effects`). Absorption II
takes the whole 4 points into the Bot's extra hearts, so no `set_health` comes, only the change
in its entity data.

`combat/death` hurts the Bot by 100 points, five times its health. The window holds the death
screen (`player_combat_kill`) and the death message that the server says in chat (`system_chat`),
both with the same text. With `show_death_messages` off, the server sends no chat message and the
text in `player_combat_kill` is empty. The game rule `immediate_respawn` stays false, as in
vanilla, so the server waits for the Bot to ask to respawn. Kinds of damage that need an attacker
are left out, because the attacker's name and UUID are in the message and the UUID differs
between servers.

A dead player still ticks in real time, and about a second after the death the server sends it
`entity_event` 60. The respawn comes well before that. If the Bot is held up for a second on one
Instance only, the event can come inside the respawn window from one server and not from the
other, so the Group fails if it comes before the respawn, as the `player` Groups that end in a
death do (see below).

## Player (`player`)

What the world does to a survival player. Each Group puts a Bot where the world hurts it and
compares what the server sends back: the damage (`damage_event`), the health (`set_health`), the
entity data (`set_entity_data`), the sounds, a correction of the player's place
(`player_position`), and a death (`player_combat_kill`, `respawn`). The server runs on normal
difficulty, because peaceful stops most damage.

Natural regeneration and random ticks are off, so nothing but the Group changes the Bot's health
or the blocks. (Mobs do not spawn either, but that is the Fixture world's rule, not the Group's.)
The Group clears the weather and stops its cycle (`advance_weather`), because rain puts out a
burning player and a storm can start on one server and not on the other. A storm fades over 100
ticks after the weather is cleared, so the Group lets the world run them before it freezes it.
A server saves a player where it leaves. Control is online before the Group starts, so it joins
where the last Group left it, which is 96 blocks from the spawn. The Group moves it there so that
its entity never reaches a window. Each Bot joins where the last play left it, and the Group puts
it back at the spawn when it ends, so that it does not rejoin inside a block. Once a Group is over,
the three rules are set back to their values and the blocks it set are removed.

A frozen world does not freeze a player: it ticks 20 times a second either way. A fall is
different, because vanilla works out its damage when it reads the move that lands. So `player/fall`
freezes the world and steps it after each move, except the landing that kills the Bot. What comes
after a death comes on the player's own ticks, so a step there would only hold back the respawn.
That window waits for the death (`player_combat_kill`), as in `player/drowning` and `player/void`,
so a server that kills the player a few ticks after the landing still has its death compared.

In those three Groups the window that holds the death closes at a barrier after it, not on
`player_combat_kill`. In vanilla, a player that dies is sent `player_combat_kill`, then entity
event 3 at once, and then the health it is left with (`set_health`, and the health in its entity
data). The barrier makes sure all of it has arrived, on every server, before the window closes. A
dead player is sent nothing else that the window compares until entity event 60, 20 ticks later,
so how long the barrier takes does not change what the window holds. The barrier holds back the
Bot's respawn request by a few ticks.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `player/fall` | tick-exact | none | A Bot falls 3, 4, 10 and 23 blocks onto stone, water, a hay bale, a slime block and a bed, in a window of its own each. Then it falls 10 blocks onto stone with `fall_damage` off, and last 23 blocks onto stone, which kills it, in a window that ends a barrier after the death. The Bot respawns in a window of its own, which fails the Group if entity event 60 comes in it before the respawn. | none |
| `player/drowning` | exact | none | A Bot with 8 health is put under water in a pool 2 blocks deep with `drowning_damage` off, and stays until it drowns, all in one window. The first time its air runs out it gets only the bubbles. Then `drowning_damage` is turned on, and four hits kill it. The Bot respawns in a window of its own, which fails the Group if entity event 60 comes in it before the respawn. | `drowning.bubbles_to_death` |
| `player/suffocation` | exact | none | A Bot is put inside a column of stone 2 blocks high and takes damage, then two more hits. | none |
| `player/void` | exact | none | A Bot is put at y -130, below the world, and takes damage until it dies. Then it respawns in a window of its own, which fails the Group if entity event 60 comes in it before the respawn. | none |
| `player/fire` | exact | none | A Bot is put in fire and takes damage. Then a fresh Bot steps into lava, out of it onto dry grass still burning, and into water. | none |
| `player/freezing` | exact | none | A Bot is put in powder snow and takes freezing damage twice. | none |

`player/drowning` compares how many air values come between two hits. Vanilla takes a point of air each tick the player is under water, so a Candidate that hurts a drowning player 40 air values apart instead of 20 sends 20 more of them between two hits, or none if it holds the air at 0. A Candidate whose air goes down a point every other tick hurts every 40 ticks and still sends the same values in the same order, so it passes: no window compares how long a tick of air lasts. The Measurement `drowning.bubbles_to_death` records it instead. It is the time from the first bubbles to the death: 80 ticks on vanilla, which is 4 seconds, and about twice that on such a Candidate. A Measurement never fails a Group.

The other Groups compare nothing that changes every tick, so a Candidate that hurts less often than vanilla sends them the same packets in the same order. `player/freezing` is sent the player's frozen ticks every tick, but leaves its entity data out, for the reason given below. These Groups do not compare how often damage repeats:

- `player/suffocation`: vanilla hurts every 10 ticks.
- `player/void`: vanilla hurts 4 points every 10 ticks until the player dies.
- `player/fire`: vanilla hurts a player in fire or lava every 10 ticks, and one still burning on dry ground every 20.
- `player/freezing`: vanilla hurts a frozen player every 40 ticks.

`player/fall` is the only tick-exact Group, and what it compares is the damage of each landing.

A Bot does not simulate physics: `player/fall` gives each position, at most 8 blocks apart. The
last move lands from 1 block above the surface, as a vanilla client's does. Before each fall, the
Bot is healed with an `instant_health` effect and put at its height with `/tp`. The surfaces are
one block wide, each in a lane of its own.

The water is a pool 2 blocks deep, and the Bot lands in it with its head above the surface. A
player under water loses air in real time, which a stepped window cannot place. The Bot also stops
in the water for one tick before it lands, because vanilla learns that a player is in water on
its own tick, after the move: a move that goes from the air into the water and lands is a fall
onto the pool's floor.

A bed leaves an item behind when it is taken away, which would stay in the Instance for the next
play and be picked up by the Bot, so the Group removes dropped items last.

A player ticks in real time, so `player/drowning` does not step the world. It makes the player
fresh (killed and respawned, with full air), takes it to 8 health with an `instant_damage` effect
(12 points), and turns `drowning_damage` off. Then one window holds the rest. The Bot is put under
water with `/tp`, and its air runs down from 300, a point a tick. When the air runs out, vanilla
sends the bubbles (`entity_event`) and, with `drowning_damage` off, no damage. The Group turns
`drowning_damage` on, and the window ends a barrier after the Bot's death (`player_combat_kill`),
four hits later. The window opens while the air is full and does not change, so it holds every value of the
air (`set_entity_data`) on every server, and with them the number of ticks between two hits. The
rule must be on before the air runs out again, 20 ticks after the bubbles. The Group checks the
order of what the Bot receives: if the next bubbles come with no hit before the bubbles after
them, the rule came too late, and the Group fails, which on the Reference is an `error`. The order
does not depend on how late the Bot reads its packets, or on how fast the server runs its ticks.

`player/suffocation` puts the Bot's feet and eyes inside stone, and `player/void` puts it at y -130:
vanilla hurts a player 4 points a hit below y -128, the lowest block minus 64, until it dies. That
window ends a barrier after `player_combat_kill`, and a second window holds the respawn.

`player/fire` has a window for each place. The first ends on the first hit in fire, the next on the
first hit in lava, and the third on the first burn after the Bot has stepped out onto dry grass.
The Bot is made fresh before the fire and again before the lava: a player is immune for 10 ticks
after a hit, and a lava tick inside them hurts only by the excess, so the lava's full hit would
fall between two windows.
The Bot leaves the lava as soon as the hit there has come, before the next window opens, so its
move onto the dry grass is in no window. If the next lava hit, 10 ticks later, reaches the Bot
before the move does, the Group fails. Leaving within those ticks also makes the burn start from
the same count of ticks on every server. The last window ends a barrier after the water puts the
fire out.
The Group masks the pitch of `sound`: the burn and extinguish sounds draw it at random. Other
sounds have a fixed pitch (a note block's is its gameplay), so the Mask is this Group's and not
every Comparison's. How the pitch is distributed belongs to a statistical Group (#24).

The hits are timed in real time, so each window must open before the next hit. The Group measures
the time since the last hit when a window opens, and fails if the next hit may already have come.
On the Reference that is an `error`, and not a Candidate's `mismatch`.

`player/freezing` compares the hits and the Bot's move into the snow, but not the entity data:
vanilla hurts a frozen player when its tick count is a multiple of 40, a count that started when the
Group made the player respawn, so the ticks before the first hit are timing.

A death is `player_combat_kill`: the player that died, and the death message as the bytes of its
text component. The player is numbered like any entity, because the id of a Bot differs between
servers, and between plays on one server.

Vanilla sends a dead player entity event 60, the smoke where its body was, 20 ticks after the
death, unless the player has respawned by then. In `player/fall`, `player/drowning` and
`player/void` the window before ends a barrier after the death, and the respawn window opens a
barrier later, so the respawn comes first. In `player/void` on vanilla, with the host under load,
the Bot asked to respawn about 300 ms after the death, and at most about 410 ms, in 40 plays. If the Bot is held up for most of a second after the death, the
event can come inside the respawn window from one server and not from the other. So the Group fails if entity event 60, for any
entity, comes inside the respawn window before the respawn, and says whether the event was for
the Bot or for another entity. On the Reference that is an `error`.
On a Candidate it is a `mismatch`, as is any failure of a Candidate's play, even when the Bot was
the one held up. A Candidate that sends the event early fails every Run, while a stall seldom
comes twice. An event 60 that comes after the death but before the respawn window opens is in
neither window, and no server is compared on it.

### Game modes, death and respawn

What a game mode changes, and what happens to a player who dies. The server runs on normal difficulty. Control stands at x 96.5 and z 96.5, out of every Bot's view, and each Bot is put back at the spawn in survival when the Group ends. The Group clears the weather and stops its cycle (`advance_weather`), because a player who respawns in rain is sent the weather, and a storm can start on one server and not on the other. A storm fades over 100 ticks after the weather is cleared, so the Group lets the world run them before any Bot joins.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `player/game-modes` | exact | none | Two Bots join, `changer` and `watcher`. Control switches the changer to creative, adventure, spectator and back to survival with `/gamemode`, in a window each. The windows compare the abilities, the game mode event and the tab list, and what the watcher is sent about the changer: its entity data, its attributes and its place on the locator bar, and whether it is removed from the watcher's view and added again. | none |
| `player/death` | tick-exact | none | Control kills a Bot in five windows. The Bot holds five diamonds, then one level of experience, both with `keep_inventory` on, five diamonds with `immediate_respawn` on, and both with both rules on. Each window sets the two rules, kills the Bot, and compares the death, the Bot's health, experience and inventory, the item or orb it drops, and the game event vanilla sends when `immediate_respawn` is set. The Bot respawns after each window. | none |
| `player/respawn` | tick-exact | none | Control kills a Bot that holds five diamonds and a level of experience, and the Bot respawns at the world spawn in a window. Then the same with `keep_inventory` on. Last, a second Bot, which stands 6 chunks away and has a spawn point at -88, -60, 88, is killed and respawns there. The windows compare the respawn, the Bot's health, experience and inventory, the spawn position, the difficulty and the world border it is sent again, and the place the server puts the Bot. | none |

In spectator mode vanilla marks the changer invisible in its entity data and sends the watcher a `waypoint`. The watcher stands 4 blocks from the changer.

A death drops at most one entity: a stack of diamonds, or an experience orb of 7 points, which is what one level of experience drops. Vanilla resends the entities a tick made in an order that follows their entity ids, and two servers can number their entities differently, so a death that dropped both would not match itself. With `keep_inventory` on, nothing drops, and the Bot holds both.

A dropped item and an orb start moving in a direction vanilla draws at random. The Group masks the speed (`velocity.x`, `velocity.y` and `velocity.z` in `add_entity`) and which way the entity faces (`yaw`). Where the entity appears, its type and its count are still compared. How the entity then moves belongs to `entities/motion`.

`immediate_respawn` is set inside the window, so that the `game_event` vanilla sends when the rule is set is compared. With the rule on, vanilla still waits for the player's request to respawn, so the Bot asks after the window in every death. Dropped items and orbs within 20 blocks of the spawn are removed after each window, because the Bot respawns there and would pick them up.

A server keeps a player's spawn point and no command clears it. The Bot that respawns at the world spawn never has one, and the second Bot, `pointer`, always has the same, so every play starts from the same state. The two Bots stand out of each other's view: a player who respawns is sent to the others in view a tick or two later, and a window cannot place that.

### Hunger (`player_hunger`)

What a survival player's food does to its health. A player's food, saturation and exhaustion
change on its own tick, and a frozen world does not freeze a player, so these Groups take real
time. Each window waits for the `set_health` that ends what it tests, then for 100 more ticks in
which nothing else may come. What is compared is the order of the values, not the tick they
come on.

Every part starts from a fresh player, killed and respawned: health 20, food 20, saturation 5.
No command sets the food, so a Group lowers it with the hunger effect for an exact number of
ticks, and sets the health with `/damage` of type `generic`, which costs no food.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `player/regeneration` | exact | none | A Bot at 10 health heals from food 20, from food 18 and from food 17, in a window of its own each. Each heal costs food, and the healing stops at 17. | none |
| `player/starvation` | exact | none | A Bot with no food starves on easy from 12 health, on normal from 3 and on hard from 2, in a window of its own each. It stops at 10 health on easy and at 1 on normal, and dies on hard. | none |
| `player/eating` | exact | none | A Bot at food 2 eats bread, cooked beef, a golden apple and rotten flesh, in a window of its own each. | none |
| `player/exhaustion` | exact | none | A Bot sprints 100 blocks, jumps 10 times, then hits 20 husks, with one window for the sprint, one for the jumps and one for the hits. After each, it reads back its food, saturation and exhaustion with `/data get`. | none |

These Groups compare what changes and in what order, not how many ticks it takes. A Candidate
that heals every 40 ticks instead of 80, or starves a player every 20, sends the same packets
in the same order. The rate needs a window that counts ticks, as for damage above. A window
knows that nothing more comes by waiting: vanilla sends `set_time` every 20 ticks, frozen or not,
so 6 of them span at least 100 ticks, more than the 80 between two heals or two hits of
starvation. A Candidate that hurts a starving player past the floor, but more than 100 ticks
after its last hit, is not seen.

In `player/regeneration` the Bot heals from saturation at food 20, every 10 ticks, and from food
alone at 18, every 80. Each heal costs food, until the food is 17 and the healing stops. In
`player/starvation`, natural regeneration is off. The damage that sets the health runs inside the
window: a respawned player takes no damage until its client says it has loaded the world, and
the window's opening barrier makes sure the server has read that.

In `player/eating` each window ends on the `set_health` that the food sends. The Group masks the
pitch of `sound`, because vanilla draws it at random for the eating and burp sounds. Rotten flesh
gives hunger 4 times in 5, at random, so its window does not compare the effects.

No packet carries exhaustion, so `player/exhaustion` has the Bot, an operator, read its food,
saturation and exhaustion back with `/data get` after each part. The Bot passes a barrier after
each move and hit, so its player ticks between two of them, as it does for a vanilla
client, and the exhaustion adds up in the same order on every server. A hit costs exhaustion only
when it hurts, and a husk is immune for 10 ticks after a hit, so the Bot hits 20 husks once each,
standing in a ring around it. The husks are killed when the Group ends, with drops off. The Bot
stays beside them until it is told the last one is gone, so that their chunk stays loaded.

Vanilla counts a jump only from a player it thinks is on the ground. Between two moves it runs
the player's own movement each tick, and for 6 ticks after a jump that movement goes up and
leaves the ground. A jump that comes sooner is not counted, so the Bot waits for 4 barriers after
each jump, at least 8 ticks, before the next.

The sprint, the jumps and the hits change neither the health nor the food, so on vanilla their windows hold
nothing, and the readback carries the comparison. The windows compare only `set_health`, not
`sound` or `entity_event`: a hit's sound and effects follow the attack charge, which grows in
real time, so the same hit can differ from one play to the next.

## Inventory (`inventory`)

What a survival player sees when it is given items, clicks them about, drops them and swaps them between its hands. Each Group joins one Bot at the world spawn, looking down, with an empty inventory. `inventory/offhand` also joins a second Bot a few blocks away. Control freezes the world, so an item on the ground stays where it fell and counts down its pickup delay only on the ticks a Group steps. When a Group ends, Control removes the items it made and empties the Bot's inventory. Items that lay there before are tagged first and left alone.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `inventory/give` | exact | none | Control gives the Bot 1, 64 and 100 stone, a diamond sword, and one stone into an inventory full of dirt, in a window of its own each, and the world steps one tick. Each window compares the slots that change, the item vanilla shows popping out of the player, which nobody can pick up and which it removes on that tick, the pickup sound, and, for the full inventory, the item that drops. | none |
| `inventory/clicks-inventory` | exact | none | The Bot clicks in every mode in its own inventory: a left and a right click, a shift-click between the inventory and the hotbar, the number keys 1 to 9 and the off-hand key, an even drag and a drag of one each, a double-click, Q and Ctrl+Q over a slot, and a click outside the menu. It also shift-clicks a diamond helmet onto its head and back, which plays the equip sound. Each click sequence has a window of its own. | none |
| `inventory/clicks-chest` | exact | none | The Bot opens a chest of stone, dirt, logs and a sword and clicks in every mode in its menu, as in `inventory/clicks-inventory`, with a shift-click each way between the chest and the Bot. Each click sequence has a window of its own, and the Bot opens the chest again at the end to compare what is in it. | none |
| `inventory/drop` | tick-exact | none | The Bot drops one stone of a stack with Q, and the world steps 41 ticks: the stone's pickup delay is 40, and the Bot picks it up on the 40th. Then it drops a whole stack with Ctrl+Q, a sword, and nothing from an empty hand, a tick each. | none |
| `inventory/offhand` | exact | none | The Bot presses F three times, in a window each: with a stack of stone in its main hand only, with a stack of torches in its off hand only, and with both. A second Bot stands a few blocks away. Each window compares the slots the server sets in the Bot's inventory and what it tells the second Bot of the swap, and the world steps one tick. Vanilla tells it with an entity event, not with the new equipment. | none |

The Bot predicts each click as the vanilla client does and sends its prediction. Vanilla sends nothing back for a click it agrees with, so a click window on vanilla is often empty. A server that resolves a click another way sends the slots it corrects, and those are compared.

Vanilla throws an item a player drops with a random motion and yaw, so these Groups compare where a dropped item appears, what it is and how many, but not how it moves. The pitch of the `/give` pickup sound and of a chest's sound is random too, and only the pitch is left out.

## Crafting (`crafting`)

What a crafting grid shows, what a click in the recipe book puts in it, and how recipes enter
and leave the recipe book. Each Group joins one Bot in survival and empties its inventory.
Control gives the Bot the items each case uses and stands at x 96.5 and z 96.5, out of view.
Every window compares the slots and the cursor as the server sets them, the ghost recipe, the
recipes added to and removed from the book, and the recipe data. When the Group ends, the Bot is
emptied and put back at the spawn.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `crafting/grid` | exact | none | A Bot, `crafter`, clicks items into the 2 × 2 grid of its inventory, one item a cell, in a window for each case: planks from a log, sticks, a crafting table, bone meal from a bone (shapeless), and two arrangements that make nothing. Then it puts two logs in one cell and takes the planks twice, a window each: onto an empty cursor, then onto the planks it holds. Last, in a crafting table, it lays out the items of two stone pickaxes (shaped) and takes a pickaxe twice. A pickaxe does not stack, so the second take finds no room on the cursor and takes nothing. | none |
| `crafting/recipe-book` | exact | none | A Bot, `bookworm`, clicks recipes in its recipe book, in a window each. In the 2 × 2 grid: planks, all the planks it can make, a crafting table with too few planks, and sticks, a recipe it does not know. Then in a crafting table: a stone pickaxe, a stone pickaxe with too little cobblestone, as many crafting tables as it can make, and sticks. | none |
| `crafting/unlocking` | exact | none | Control gives a Bot, `learner`, the stick recipe and takes it, then gives and takes every recipe, in a window each. With `limited_crafting` on and then off, the Bot clicks an oak log into its grid while it knows no recipe. Last, Control revokes the advancement that unlocks oak planks and gives the Bot an oak log, which unlocks the recipe again. | none |

A recipe book click names the recipe by the number the server gave it in the player's book.
`crafting/recipe-book` gives the Bot each recipe it clicks and reads the number from the
`recipe_book_add` the server sends. A server that sends none within 10 seconds fails the Group,
and the Report names the recipe.

Each server picks these numbers, and the numbers of recipe groups, its own way. mscts numbers
the recipes again in the order each Bot gets them in a window. A recipe the Bot gets outside the
windows is named by what it shows instead, and a group is written as the recipes it holds. A
recipe keeps its number when the server gives it another number later, until the Bot logs in
again. It keeps its name while the book holds it. So a server that numbers its recipes and
groups another way but keeps to it shows the same recipe book, and so does a server that gives
and takes a recipe outside the windows. A removal of another recipe, or a recipe put in another
group, differs. If one server alone takes a recipe outside the windows and both give it again in
a window, it is a number on one side and a name on the other, and that differs too. Two recipes
that show the same are written the same, so a removal does not show which of them went. If one
`recipe_book_add` holds two such recipes in different groups, they are compared in the order each
server sent them, so a server that sends them in the other order differs, though the book shows
the same buttons. No two vanilla recipes show the same. The order
of the book's buttons is not compared. It follows the server's numbers, how many recipes the
book has held since the Bot joined, and the order the recipes came in.

A player unlocks recipes when an item first enters its inventory, once per player. The
`recipe-book` Bot gets every item it uses before its book is emptied, so that no case unlocks a
recipe of its own. A grid holds the items it was given until it is cleared. `/clear` empties the
inventory's grid as well, and a crafting table gives its grid back when it is closed, so the
Bot opens the table for each click and closes it after.

The Bot takes a crafted result with a click, never with a shift-click. A shift-click crafts
again for as long as the grid makes the same result, and the Bot cannot tell how long that is
without knowing the recipes.

## Entities (`entities`)

Entities are matched by the order they appear, not by their ids, which differ between servers.

A Bot called `watcher` stands at the spawn. Control summons, changes and kills entities a few
blocks away, one entity a window. A window compares what the watcher is told about the entity:
its spawn (`add_entity`, and the `bundle_delimiter`s around it), its data (`set_entity_data`),
its attributes, its equipment and head, its damage and death events, and its removal. The server
runs on normal difficulty, because peaceful removes a hostile mob.

The world is frozen (`/tick freeze`), so nothing moves unless a Group steps it. Every entity is
summoned with NBT, which makes vanilla skip what it draws at random for a new mob: its
equipment, whether it is a baby, and its attribute bonuses. Mobs cannot think (`NoAI`), and the
other entities do not fall (`NoGravity`). When a Group ends, Control kills the entities it
summoned, and the watcher waits until it is told the last body is gone.

Every entity stands in the chunk the watcher stands in. A server tells a player about an entity
only once it has sent the player the entity's chunk, and the watcher's join waits only for the
chunks around the spawn.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `entities/summon` | exact | none | Control summons a pig, a cow, a light blue sheep, a chicken, a zombie, a skeleton holding a bow, a creeper, a plains farmer villager, an armor stand, an item frame holding a diamond, an oak boat, a minecart, an arrow, a snowball, an experience orb worth 5, a falling sand block and a primed TNT with 40 ticks of fuse left, each facing west, in rows of 8, 2 blocks apart. | none |
| `entities/data-changes` | exact | none | Control changes one zombie a way at a time: a custom name that shows, glowing, silent, no gravity, on fire, invisible (`/effect give`) and a movement speed of 0.5 (`/attribute`). Each window steps the world once. | none |
| `entities/death` | tick-exact | none | Control kills a pig, then a zombie, with `/kill`. Each window steps the world 20 ticks, until the body is removed. | none |

Some changes show only when the entity ticks: it is on fire, or invisible, from its next tick on.
A zombie that ticks in daylight catches fire at random, so the zombie of
`entities/data-changes` has a block over its head.

The mobs of `entities/death` drop nothing, and `/kill` drops no experience. A drop would be a
second entity changed in the tick of the death. Vanilla sends the data of every entity a tick
changed at the end of that tick, in an order that follows their entity ids, so the two packets
could come in either order ([#320](https://github.com/ericbstie/mscts/issues/320)). How many
items a pig or a zombie drops is also random.

### Dropped items

How items on the ground merge, despawn and are picked up. Each Group joins one Bot at the world spawn and freezes the world. Control summons every item still and without gravity, so an item changes only on the ticks a Group steps. When a Group ends, Control removes the items it summoned and empties the Bot's inventory.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `entities/item-merge` | tick-exact | none | Control lays eight pairs of items in a row, a tick apart: two stacks of stone 0.7 blocks apart and 0.8 apart, 0.2 above each other and 0.3 above, 0.7 apart with a glass pane between them, stone next to dirt, 40 stone next to 30, and 32 next to 32. The world steps 41 ticks, until each pair has had its 40th tick. The window compares which item of a pair goes and how many items the other then holds. | none |
| `entities/item-despawn` | tick-exact | none | Control summons a stone aged 5998 ticks, a dirt aged 5997, an experience orb aged 5996, and a stone aged -32768, which never ages. The world steps 5 ticks, and the window compares when each one goes. Vanilla removes an item or an orb when its age reaches 6000. | none |
| `entities/item-pickup` | tick-exact | none | Items and experience orbs appear at the feet of a Bot that stands still, each in a window of its own. A stone with no pickup delay appears inside its window. Stones with a delay of 10 and of 40 ticks appear before theirs, and the world steps a tick past the delay. Orbs of 1, 7 and 37 points appear inside their windows. Last, a stone appears by the Bot with a full inventory, and then ten stones by a stack with room for four, and the world steps 2 ticks each time. Each window compares the pickup, the Bot's slots and experience, and the item or orb that appears and goes. | none |

An item looks for another to merge with only on every 40th of its own ticks. The pairs are laid a tick apart so that each pair merges on a tick of its own. Vanilla sends the entity data that changes in one tick in an order that follows the entity ids, and two servers can number their entities differently.

A frozen world does not freeze its players, so the Bot picks up what it can reach on every tick. A pickup delay counts down only on the ticks the world steps, so a stone is picked up on the tick its delay reaches 0. A player takes one orb in its reach each tick, chosen at random, so each orb has a window of its own. The three orbs add up to 45 points, which stays under level 5: vanilla's level-up sound depends on how long the player has been in the game.

Whether two orbs merge depends on their entity ids in vanilla, so `entities/item-merge` lays no orbs.

## Mobs (`mobs`)

How a zombie finds, reaches and attacks a player who stands still. A mob's AI draws on a random
source of its own, so no two plays go the same way, on one server or on two. These Groups are
statistical: each plays many times on each server, and its Verdict compares how the samples are
spread ([#24](https://github.com/ericbstie/mscts/issues/24)). They run only with
`--statistical`.

Each play joins a Bot of its own, puts it in place, and has Control build what the play needs.
Control makes the Bot an operator, so that the Bot can read the game time itself
(`/time query gametime`), and freezes the world.

Then Control summons the mobs, reads the game time and steps the world a fixed number of ticks:
the play's tick budget. Whenever the Bot is told of something a sample is about, such as the
zombie moving, a hit (`damage_event`) or a door breaking, it reads the game time again. It goes
on reading what the server sends while the answer is on its way, so an event that comes in the
meantime is read when it arrives. A sample is the number of ticks between the two readings,
less the play's offset.

A reading sent in reply to a packet can come back a tick late: vanilla answers it before its
next tick, Pumpkin a tick after. Each play measures this during its step. Every 20 ticks a
server sends each player the game time (`set_time`) as it was before the tick that sends it.
When the Bot receives the first one sent during the step, it reads the game time, and how far
the answer is past the end of that tick is the play's offset.

A play that runs out of ticks records nothing for what did not happen. When the play ends,
Control kills the mobs and anything they dropped, waits until the Bot is told they are gone,
takes the blocks away, and makes the Bot an ordinary player again.

Each zombie is summoned with NBT, which makes vanilla skip what it draws at random for a new
mob: its equipment, whether it is a baby, and whether it can break doors. It wears a leather
helmet, so that it does not burn in daylight, and it never despawns.

| Id | Kind | Runs | What it does | Samples |
| --- | --- | --- | --- | --- |
| `mobs/chase-open` | statistical | 25 | A zombie appears 16 blocks east of the Bot, on open ground. The world steps 300 ticks. | `chase_open.moved`: the tick the zombie is first half a block closer. `chase_open.hit`: the tick it first hurts the Bot. |
| `mobs/chase-maze` | statistical | 20 | The same, with an oak fence across the way, 8 blocks east of the Bot, with one gap 4.5 blocks off the line. The zombie sees the Bot over the fence but cannot jump it. The world steps 400 ticks. | `chase_maze.gap`: the tick the zombie gets into the gap. `chase_maze.hit`: the tick it first hurts the Bot. |
| `mobs/doors-hard` | statistical | 15 | On hard difficulty, a zombie that can break doors stands in a pen of oak fences with an oak door on its west side. The Bot stands 3 blocks from the door, in the zombie's sight. The world steps 400 ticks. | `doors_hard.started`: the tick the door first cracks. `doors_hard.broken`: the tick it breaks. |
| `mobs/doors-normal` | statistical | 10 | The same pen on normal difficulty, where vanilla's zombies break no doors. The world steps 300 ticks. | `doors_normal.door`: `held`, `cracked` or `broken`. |
| `mobs/targets` | statistical | 15 | At noon, a zombie stands 8 blocks east of the Bot, and a villager without a job 8 blocks east of the zombie. The world steps 300 ticks. | `targets.first`: whom the zombie hurts first, `player`, `villager` or `none`. `targets.hit`: the tick it does. |

A zombie breaks doors only on hard, and a Group plays on one difficulty, so the doors have two
Groups. A zombie looks for a player before a villager, and must see the player but not the
villager. The time stays at noon in `mobs/targets`, since what a villager does follows the time
of day.

## Fluids (`fluids`)

How far and how fast water and lava spread, when they make a new source, and what they turn into
where they meet. A Bot called `watcher` stands at the spawn. Control replaces the grass of the
spawn chunk with stone, builds what a Group needs on it, stops random ticks and freezes the world.
Then, in one window, Control places each fluid with `/setblock` and steps the world one tick at a
time. The window compares the blocks that change on each tick (a fluid's level is part of its
block state), the fizz of lava meeting water (`level_event` 1501), and any sound.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `fluids/water-spread` | tick-exact | none | Control places a water source in the middle of the floor, and a tick later a second one 3 blocks from a hole in the floor. The world steps 36 ticks. Vanilla spreads water one block every 5 ticks, a level lower each time, up to 7 blocks out, and only toward a hole within 4 blocks. | none |
| `fluids/lava-spread` | tick-exact | none | The same, with lava, the second source 2 blocks from the hole. The world steps 92 ticks. Vanilla spreads lava one block every 30 ticks, 2 levels lower each time, up to 3 blocks out, and only toward a hole within 2 blocks. | none |
| `fluids/sources` | tick-exact | none | Control builds four stone channels 3 blocks long and places a source at each end of each, a tick apart: two of water and two of lava. The world steps 62 ticks. With `water_source_conversion` or `lava_source_conversion` on, vanilla turns the block between two sources into a third source. Control turns each rule on for the first pair of its fluid and off for the second. | none |
| `fluids/interactions` | tick-exact | none | Control builds four cases in stone walls and places their fluids a tick apart: water flowing onto a lava source, lava flowing onto a water source, a lava source above water in a pit, and lava flowing onto soul soil beside blue ice. The world steps 63 ticks. Vanilla turns the lava into obsidian, cobblestone, stone and basalt, each with a fizz. | none |

Each fluid is placed a tick or more after the last one, so that no two placements reach the Bot
together. In a frozen world the scheduled ticks of the fluids run only on the ticks the world
steps, so each placement takes effect on the tick its delay says. A window lasts until every
source has had its last scheduled tick, which leaves none due for the next play.

## Redstone (`redstone`)

When repeaters, comparators, torches, observers and dust switch, tick by tick, in what order
dust updates the blocks around it, how pistons push, pull and power up, and when hoppers move
items. A Bot called `watcher` stands at the spawn. Control stops
random ticks, freezes the world, and builds what a Group needs with `/setblock` on the grass of
the spawn chunk. Then, in an Observation window, Control places and removes the blocks that power
each circuit and steps the world one tick at a time. The window compares the blocks that change
on each tick, a piston's block event, a torch burning out (`level_event` 1502), and any sound.
Whether a component is powered, whether a torch is lit and how strong a dust is are all part of a
block's state.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `redstone/repeater` | tick-exact | none | Control powers four repeaters with delays 1 to 4, a locked repeater, and a repeater with a delay of 4 for a single tick. Later it removes their inputs and the lock. The world steps 19 ticks. Vanilla switches a repeater 2 ticks per unit of delay after its input changes, turns the locked one on only once its lock is gone, and stretches the 1-tick pulse to 8 ticks. | none |
| `redstone/comparator` | tick-exact | none | Control powers a comparator in compare mode and one in subtract mode from behind, each with a signal of 14 at its side, then removes the side signals. A third comparator reads a chest behind it, which Control fills with 1 stack, then 4, then empties. The world steps 19 ticks. Vanilla switches a comparator 2 ticks after its inputs change: the compare one outputs 15, the subtract one 1 and then 15, and the chest's one 1, 3 and 0, which the dust after each shows. | none |
| `redstone/torch` | tick-exact | none | Control powers the block under a torch and takes the power away 4 ticks later, then does the same to a second torch 8 times, every 4 ticks. It steps the world 155 ticks at once outside any window, then 5 ticks more. The windows step 43 ticks in all. Vanilla turns a torch off 2 ticks after its block is powered and on 2 ticks after the power goes. The 8th time the second torch turns off within 60 ticks, it burns out, and it lights again 160 ticks later. | none |
| `redstone/observer` | tick-exact | none | Control places stone in front of an observer, then takes it away. Then it places a third observer facing a second one, which faces it back, and takes it away 12 ticks later. The world steps 30 ticks. Vanilla powers an observer for 2 ticks, 2 ticks after the block in front of it changes, and also once after `/setblock` places it. The two observers facing each other pulse in turn, a clock that stops when one goes. | none |
| `redstone/dust` | tick-exact | none | Control powers a line of 16 dust for one tick. Then, a tick apart, it places dust beside a lone dust, turns that dust into stone, puts dust on the stone, and puts stone above the lone dust, then takes them away. The world steps 10 ticks. Vanilla changes dust in the tick its neighbour changes: the line's strength falls by 1 a block, from 15 to 0 at the 16th, and the lone dust connects to the dust beside it, climbs onto the stone, and loses the climb while stone is above it. | none |
| `redstone/update-order` | tick-exact | none | Control builds two copies of one case at different places: a dust between two blocks of stone, and beside each stone a piston, both facing the same block. It powers and unpowers each dust, 5 ticks apart. The world steps 21 ticks. Vanilla updates the blocks around a dust in an order set by where the dust is, so only the piston it updates first extends: the north one in the first copy, the south one in the second. | none |
| `redstone/piston-push` | tick-exact | none | Control builds a row of pistons, each facing 1, 12 or 13 stones, obsidian, bedrock, a chest, an extended piston, a torch or a poppy. It powers each piston with a redstone block, the poppy's 2 ticks after the rest, and takes each power away 4 ticks later. The world steps 10 ticks. Vanilla pushes 1 and 12 blocks, and moves nothing when the row is 13 long or the first block is one that cannot move: that piston does nothing at all. The torch and the poppy break, each into an item. A piston acts on the tick after its power changes, and its blocks are in place 2 ticks later. | none |
| `redstone/sticky` | tick-exact | none | Control builds four sticky pistons: two facing a stone, one facing a slime block with a stone and a honey block beside it, and one facing a honey block with a stone and a slime block beside it. It powers all four, takes one stone's power away after a single tick, and the rest 5 ticks later. The world steps 9 ticks. Vanilla pulls each block back when the power goes, but the piston powered for a single tick leaves its stone where it pushed it. The slime and honey blocks take the stones beside them along, and leave each other behind. | none |
| `redstone/quasi-connectivity` | tick-exact | none | Quasi-connectivity is a vanilla behaviour in which a piston, a dropper or a dispenser also counts power at the block above it, but checks for power only when a block next to it changes. Control places a redstone block 2 above a piston, a dropper and a dispenser, then a stone behind each 2 ticks later. 6 ticks after that it takes the redstone blocks away, and 2 ticks later the stones. The world steps 14 ticks. Vanilla does nothing when the redstone blocks arrive or go, only when the stones do: the piston extends and the dropper and the dispenser click, then the piston retracts. | none |
| `redstone/hopper-transfer` | tick-exact | none | A chest holds a stone in its first slot and 2 logs in its third. It stands on a hopper that holds a dirt in its second slot and faces a second hopper, which faces an empty chest. The world steps 32 ticks. Vanilla moves one item from each hopper every 8 ticks. A hopper pushes from its first slot that holds anything, then pulls from the first slot above it that holds anything. The second hopper pushes each item 7 ticks after it arrives, and the logs stack in the last chest. | none |
| `redstone/hopper-full` | tick-exact | none | A hopper holding 3 dirt faces a chest with a full stack of stone in every slot. After 3 ticks, Control takes one stone from a stack, and 3 ticks later it empties another slot. The world steps 23 ticks. Vanilla moves nothing into the full chest, and no dirt onto the stone. A hopper that moved nothing tries again on the next tick, so it pushes a dirt on the tick after the slot empties, then every 8 ticks. | none |
| `redstone/hopper-pickup` | tick-exact | none | Three hoppers face down: one with nothing above it, one under a stone and one under a bottom slab. Control summons an item lying above each, then a second item above the first hopper 2 ticks later. The world steps 9 ticks. Vanilla's first hopper takes the first item on the first tick and the second item 8 ticks later. The hopper under the slab takes its item through the slab, and the one under the stone never takes the item lying on the stone. | none |

The piston Groups also compare block entities' data and the items a piston breaks a block into.

In the hopper Groups, a Bot stands beside each hopper and chest and opens it before the world
steps. Their windows compare what each open container shows, and `redstone/hopper-pickup` also
compares the items that appear and go. Vanilla sends a hopper's move to
an open container in the next server tick, which a frozen world runs too, so it arrives before
the step ends. When a Group ends, the Bots close
the containers and the world steps 5 more ticks, because an open chest checks again for its
players 5 ticks after the last check.

The Groups with pistons mask the pitch of `sound`: vanilla draws a piston's pitch at random.
Which sound plays, where and at what volume is still compared. `redstone/piston-push` also
masks where each item a piston breaks a block into appears and how it moves, which vanilla also
draws at random. Which item it is, and how many, is still compared.

Vanilla sends no comparator's output strength: it is kept in the comparator's block entity, not
in its block state. So each comparator has dust after it, whose strength shows the output.

In a frozen world, scheduled ticks run only on the ticks the world steps, so each change takes
effect on the tick its delay says. A window lasts until the last component has switched, so that
no tick is left due: the server would save it with the chunk, and it would run in the next play.
When a Group ends, Control clears what it built with `/fill ... strict`, which updates none of
the blocks beside the ones it clears, so it schedules no tick either.

## Spawning (`spawn`)

Where a new player first appears. Vanilla spreads new players over the blocks within `respawn_radius` of the world spawn, 10 by default, instead of stacking them on one block, and picks a safe one. Both Groups are `statistical`: each plays many times on each server and compares the distributions of what it records, and `mscts run` plays them only with `--statistical` (see [Writing a Group](/guide/writing-a-group)).

In each play, Control sets the world spawn to the block at 0, -60, 0 (`/setworldspawn 0 -60 0`) and a player joins under a name that no earlier play of the Run used. Vanilla keeps a player's position when it leaves, so a name that joined before comes back where it left. Each play records four samples, which are the test cases: how far the player stands east (`spawn.x`) and south (`spawn.z`) of the middle of the spawn block, its height (`spawn.y`) and its distance from the middle of the block (`spawn.distance`).

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `spawn/join-position` | statistical | none | A new player joins with `respawn_radius` at its default. Vanilla places it on a random block within 10 blocks of the spawn along each axis. | none |
| `spawn/join-position-exact` | statistical | none | The same, with `gamerule respawn_radius 0` and the check that repeats a join's first position off (`gamerule player_movement_check false`). Vanilla places every player on the spawn block's column. Once the player has joined, both rules are set back to vanilla's defaults, not to the values the server had before. | none |

## Time (`time`)

How the time of day moves, what the time commands set and answer, and whether sleeping skips
the night. Each Group joins a Bot called `clock`, an operator, which reads the time back with
`/time query`. Control freezes the world, stops the weather and clears the sky. When a Group
ends, every rule it changed is set back to vanilla's default.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `time/advance` | tick-exact | none | From day 1000, the world steps 1, 20 and 100 ticks, with `advance_time` on and then off. After each step, the clock reads `time query day` in a window of its own. | none |
| `time/commands` | exact | none | From total ticks 0, the clock sets the time to `day`, `noon`, `night` and `midnight`, reading `time query time` after each. It then sets 1000, adds 100 and reads `time query day`, adds 24000, and reads `time query day`, `time query day repetition`, `time query time` and `time query daytime`. Each command has a window of its own. | none |
| `time/sleep` | exact | none | A second Bot, `sleeper`, lies down in a bed at midnight while the clock stays up. With `players_sleeping_percentage` 100 the night goes on for 100 ticks, then the world steps to dawn and the sleeper gets up. With 50 the clock reads the day at most 60 ticks after the sleeper lies down, and then the night is skipped. The clock reads the day after each part. | none |

In 26.3 the time of day is a world clock, separate from the game time. `time query day` answers
how far into the day the clock is, `time query day repetition` how many days have passed, and
`time query time` its total ticks. `time query daytime` no longer exists, and vanilla answers it
with an error. `time query gametime` is not compared: the game time counts every tick since the
world was made, so two servers started at different moments answer differently
([#399](https://github.com/ericbstie/mscts/issues/399)).

The server also sends the time in `set_time`, every 20 ticks and whenever a command changes it.
No window compares `set_time`, because how many arrive depends on how long a window lasts
([#63](https://github.com/ericbstie/mscts/issues/63)). The Groups use it only to know when a
step has ended: its game time shows how many ticks have run.

In `time/sleep` Control leaves before the sleeper lies down, so the two Bots are the only
players while it does: with 50% needed, one sleeper of two is enough. Control is back for the
step to dawn, so three players are online when the sleeper is woken.

A player falls into a deep sleep 100 of its own ticks after it lies down, and a frozen world
does not freeze its players, so the night is skipped about 5 seconds later whatever the world
does. The windows compare the sleep messages, the sleeper leaving its bed, its pose and the
game events in the order they come, not the tick they come on. To check that the night is not
skipped too soon, the clock reads the day at most 60 ticks after the sleeper lies down. Vanilla announces the advancement for sleeping in a bed and the new
spawn point only the first time a player sleeps, so Control takes both back before the sleeper
lies down. Control steps the world to dawn inside a window, and an operator sees Control's
commands as chat, so the clock is no operator during that step.

## Planned

| Mechanic | First Group | Needs |
| --- | --- | --- |
| Redstone glitches | Tick-by-tick observation under `/tick freeze` and `/tick step`, as in [Redstone](#redstone-redstone) | Their Groups. The `tick-exact` kind they use exists. |
| Mob spawning and loot | Distributions over many runs | Its Groups. The `statistical` kind they use exists, in its own opt-in tier. |
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
| `drowning.bubbles_to_death` | ms | The `drowning.bubbles_to_death` span in `player/drowning`: from the first bubbles to the death. |
| `instance.startup` | ms | Every Run: from launching a server until it is ready. |
