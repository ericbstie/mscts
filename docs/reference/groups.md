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

The `/fill` region holds one block that drops an item. Vanilla sends the items a tick drops in an
order that follows their entity ids, and two servers can number their entities differently, so with
several items the Reference would not match itself.

### Blocks a player breaks and places

Two Bots, `digger` and `watcher`, join. The digger breaks and places blocks. The watcher stands
beside it, because vanilla does not send the cracks and break particles of a dig to the player who
digs. Control puts the digger, the watcher and itself at x 8.5, 12.5 and 4.5, y -60, z 4.5, with
`/tp`, before the first window, and sets each case up with `/setblock`, `/fill`, `/summon`,
`/item replace entity` (the tool or the stack the digger holds, in its first hotbar slot) and
`/kill`. The world is frozen and random ticks are off. The Groups require all of those commands.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `blocks/dig-creative` | tick-exact | none | In creative mode, the digger breaks stone, dirt and obsidian by hand, each in one window, then tries stone with an iron sword, which cannot break blocks. | none |
| `blocks/place` | tick-exact | none | The digger places stairs and logs on each of the six faces of a stone block, stairs while facing each of four ways, and a slab (bottom, top and doubled). | none |
| `blocks/place-attached` | tick-exact | none | The digger places a door with the cursor on each side of the block, a torch (on top and on each side), and a bed facing each of four ways. Then it places stone onto short grass and onto a snow layer, which it replaces, and into the space of an armor stand, which the server refuses. | none |

A dropped item has the same Masks as in the commands above: where it appears, its sideways speed and
which way it faces.

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
health (`set_entity_data`), its velocity (`set_entity_motion`), the sounds and the particles.
It leaves out the husk's position packets: vanilla resends the position of a husk that stands
still about every 3 seconds, so one lands in a window now and then.

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

Vanilla sends the data and the velocity of every entity a tick changed at the end of that tick, in
the order of a hash of their entity ids, and the two Instances' ids differ. So when a hit changes
two entities, the order of their packets differs between runs of vanilla itself. A sprinting hit
changes the husk's health and the fighter's sprint flag, which the hit clears. So the windows of
the sprinting hits in `combat/critical`, `combat/knockback` and `combat/pvp` leave out
`set_entity_data`, and the health of the husk is read back; the victim's is in `set_health`.
Whether the sprint stops is not compared. A rule that ignores the order of the tick-end resends
of several entities (#320) would let it be. The window of `combat/sweep` compares only the damage,
the sounds and the particles, because the sweep hurts four husks, and the health and velocity of
each husk are read back.

In `combat/knockback` the husk's velocity and position, in the window and in the readback, say how
far a sprinting hit knocks it back.

A Player keeps its health and its food from play to play, so each Bot is given health and
saturation (`effect give`) before the first hit. In `combat/immunity` the tapper stands a block
behind the striker, out of the sweep of the striker's sword. `combat/pvp` runs with player
versus player damage on, which is the server default; a server with it off is not covered.

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
| `combat/death` | tick-exact | none | The Bot takes 100 points of `generic`, `fall` and `magic` damage with `show_death_messages` on, and of `generic` damage with it off. Each death has a window, and the respawn after it has another. | none |

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
`entity_event` 60. The respawn comes well before that. A host that stalls for a second on one
Instance only can show it as a Divergence in the respawn's window.

## Player (`player`)

What the world does to a survival player. Each Group puts a Bot where the world hurts it and
compares what the server sends back: the damage (`damage_event`), the health (`set_health`), the
entity data (`set_entity_data`), the sounds, a correction of the player's place
(`player_position`), and a death (`player_combat_kill`, `respawn`). The server runs on normal
difficulty, because peaceful stops most damage.

Natural regeneration and random ticks are off, so nothing but the Group changes the Bot's health
or the blocks. (Mobs do not spawn either, but that is the Fixture world's rule, not the Group's.)
A server saves a player where it leaves. Control is online before the Group starts, so it joins
where the last Group left it, which is 96 blocks from the spawn. The Group moves it there so that
its entity never reaches a window. Each Bot joins where the last play left it, and the Group puts
it back at the spawn when it ends, so that it does not rejoin inside a block. Once a Group is over,
the two rules are set back to their values and the blocks it set are removed.

A frozen world does not freeze a player: it ticks 20 times a second either way. A fall is
different, because vanilla works out its damage when it reads the move that lands. So `player/fall`
freezes the world and steps it after each move.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `player/fall` | tick-exact | none | A Bot falls 3, 4, 10 and 23 blocks onto stone, water, a hay bale, a slime block and a bed, in a window of its own each. Then it falls 10 blocks onto stone with `fall_damage` off, and last 23 blocks onto stone, which kills it. The Bot respawns in a window of its own. | none |
| `player/drowning` | exact | none | A Bot is put under water in a pool 2 blocks deep and stays until it takes damage, then for three more hits. Then `drowning_damage` is turned off, and the Bot stays for one more round of bubbles. | none |
| `player/suffocation` | exact | none | A Bot is put inside a column of stone 2 blocks high and takes damage, then two more hits. | none |
| `player/void` | exact | none | A Bot is put at y -130, below the world, and takes damage until it dies. Then it respawns. | none |
| `player/fire` | exact | none | A Bot is put in fire and takes damage. Then a fresh Bot steps into lava, out of it onto dry grass still burning, and into water. | none |
| `player/freezing` | exact | none | A Bot is put in powder snow and takes freezing damage twice. | none |

What these Groups do not compare is how often damage repeats. A window holds what one hit sends, and a Candidate that hurts a drowning player every 40 ticks instead of 20, or a suffocating one every 20 instead of 10, sends the same packets in the same order. The same holds for `player/void` and `player/freezing`: nothing in them depends on time. `player/fall` is the only tick-exact Group, and what it compares is the damage of each landing. The rate of damage needs a window that counts ticks, which these Groups do not have yet.

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

A player ticks in real time, so `player/drowning` does not step the world. It puts a fresh player
(killed and respawned, with full air) under water with `/tp` inside its first window, which ends on
the first `set_health` the Bot receives: the 300 ticks of air and the damage. Each
later hit has a window of its own that compares only what the hit sends (`damage_event`,
`entity_event`, `set_health`, `sound`). The entity data changes every tick, and a window that opens
after a hit starts a tick or two later on one server than on another. With `drowning_damage` off,
vanilla still resets the air and sends the bubbles, and sends no damage.

`player/suffocation` puts the Bot's feet and eyes inside stone, and `player/void` puts it at y -130:
vanilla hurts a player 4 points a hit below y -128, the lowest block minus 64, until it dies. That
window ends on `player_combat_kill`, and a second window holds the respawn.

`player/fire` has a window for each place. The first ends on the first hit in fire, the next on the
first hit in lava, and the third on the first burn after the Bot has stepped out onto dry grass.
The Bot is made fresh before the fire and again before the lava: a player is immune for 10 ticks
after a hit, and a lava tick inside them hurts only by the excess, so the lava's full hit would
fall between two windows.
The Bot must leave the lava within 9 ticks of its last hit, so that the burn starts from the same
count of ticks on every server. The last window ends a barrier after the water puts the fire out.
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

### Game modes, death and respawn

What a game mode changes, and what happens to a player who dies. The server runs on normal difficulty. Control stands at x 96.5 and z 96.5, out of every Bot's view, and each Bot is put back at the spawn in survival when the Group ends.

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

## Planned

| Mechanic | First Group | Needs |
| --- | --- | --- |
| Redstone and glitches | Tick-by-tick observation under `/tick freeze` and `/tick step` | Its Groups. The `tick-exact` kind they use exists. |
| Spawning and loot | Distributions over many runs | The `statistical` kind, in its own opt-in tier. |
| Survival digging | `blocks/dig-survival`: finishing a dig early and on time | [#347](https://github.com/ericbstie/mscts/issues/347): the server's rule for accepting a finish is not known yet. |

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
