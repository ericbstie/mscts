# Test case reference

Search the name from a Report to find what mscts compared and what a
difference means. A test case without an entry is still reported by name.
See [Reading a Report](/guide/reading-a-report#test-cases) for how names
describe packet fields and list elements.

## `add_entity`

**Entity appearing**

A packet that tells the client an entity appeared, such as the item a
broken block drops. A server that leaves it out shows no item. Where an
item appears, how it moves and which way it faces are left out of the
comparison, because vanilla draws them at random.

## `add_entity.entity_uuid`

**Entity UUID**

The UUID of an entity that appears. For another player, it is that
player's UUID, the same one their player list entry holds.

## `block_entity_data`

**Block entity data**

The data a block holds, such as the text of a sign. A server that leaves
it out, or sends other data, shows a blank sign or different text. A
chest's items are not sent in it. The `blocks` Groups read them with a
command instead and compare the answer as `system_chat`.

## `block_update`

**Single block change**

One block changing at one position, as `/setblock` does. A server that
sends a change vanilla does not, or leaves one out, shows the player a
different world. Its fields have their own test cases, below.

## `block_update.block_state`

**Single block change state**

The state the block changes to. Each combination of a block and its
properties, such as which way a stair faces, has its own number, so a
different number shows a different block or a differently turned one.

## `block_update.pos.x`

**Single block change x**

The x coordinate of the block that changes. A different value changes a
different block.

## `block_update.pos.y`

**Single block change y**

The y coordinate of the block that changes. A different value changes a
different block.

## `block_update.pos.z`

**Single block change z**

The z coordinate of the block that changes. A different value changes a
different block.

## `change_difficulty`

**Difficulty**

The world's difficulty and whether it is locked, which the client shows
in its settings.

## `chunk_batch_finished`

**End of a chunk batch**

A server sends chunks in batches, each between a start and an end
packet. The client uses them only to decide how fast to ask for more
chunks, and two vanilla servers can split the same chunks into
different batches. So an end packet that only one server sent is
network traffic only.

## `chunk_batch_finished.batch_size`

**Chunks in a batch**

How many chunks the batch held. Like the batches themselves, a
different count is network traffic only.

## `chunk_batch_start`

**Start of a chunk batch**

The packet before a batch of chunks. As with the end of a batch, a start
packet that only one server sent is network traffic only.

## `commands.nodes[]`

**Command node**

One node of the command tree the server sends when a player joins: a
literal word, an argument, or the root. The client uses the tree to
suggest, complete and check the commands a player types. If vanilla
sends a node that another server leaves out, the client does not know
that command, or that part of it. Each node's fields have their own test
cases, below.

## `commands.nodes[].children[]`

**Command node child**

The position, in the list of nodes, of a node that can follow this one.
Positions depend on the order the server lists its nodes in, so a server
that lists the same tree in another order differs here too.

## `commands.nodes[].flags`

**Command node flags**

What kind of node it is (root, literal or argument), whether a command
can end there, whether it redirects, and whether it asks the server for
suggestions.

## `commands.nodes[].name`

**Command node name**

The word of a literal node, such as `gamerule`, or the name of an
argument, such as `targets`.

## `commands.nodes[].parser`

**Command argument type**

The type of an argument node, such as `minecraft:entity` or
`brigadier:string`. The client parses and checks what a player types
with it.

## `commands.nodes[].properties`

**Command argument properties**

The settings of an argument's type, such as whether a string argument
takes one word or the rest of the line.

## `commands.nodes[].redirect_node`

**Command redirect**

The node this one continues at. For example, `/execute` loops back to
its own options, and an alias such as `/tell` points to `/msg`.

## `commands.nodes[].suggestions_type`

**Command suggestions source**

Where the client gets suggestions for an argument, such as asking the
server as the player types.

## `configuration:custom_payload.channel`

**Configuration plugin message channel**

The channel a plugin message names in the configuration phase. It says which mod or plugin the message data is for.

## `configuration:update_tags.tagged_registries[].registry`

**Tagged registry name**

The name of the registry a set of tags belongs to, such as `minecraft:block`. A different name means the tags apply to another registry.

## `container_set_content`

**Inventory contents**

Every slot of the container the player has open. At a join, this is the
player's own inventory.

## `configuration:custom_payload.data`

**Configuration plugin message data**

The data of a plugin message sent while the player is being configured.
Vanilla sends one on the `minecraft:brand` channel. It holds the
server's name, which the client shows on its debug screen.

## `forget_level_chunk`

**Chunk unloaded**

The server tells the client to unload the chunk at a position, shown
like `chunk 3 -2`. A server that unloads another chunk, or leaves one
loaded, shows the player a different world.

## `game_event`

**Game event**

A change of game state the client applies, such as the game mode
changing or the client being told to wait for the chunks around it.

## `initialize_border`

**World border**

The world border's centre, size and warning distances.

## `level_chunk_with_light`

**Chunk**

A chunk only one server sent, shown by its chunk coordinates, such as
`chunk 3 -2`. The client keeps chunks by position, so neither the order
of chunks nor the batch each one comes in is compared, unless something
that depends on the order comes between them. Differences inside a chunk
that both servers sent have their own test cases, below.

## `level_chunk_with_light.sections[].block_states`

**Blocks in a chunk section**

The block at each position of one 16-block-high section of a chunk.
Servers can encode the same blocks in different ways; that difference is
network traffic only. A section's palette is the list of blocks its
positions refer to. Its order is not compared at all, because vanilla
itself sends the same section with its palette in different orders. A
different block is shown at its position in the world, with each
server's block state id at that position, such as
`chunk 2 -1: 37 -62 -9 is 10`. The first three positions that differ are
named, and the rest are counted.

## `level_chunk_with_light.sections[].biomes`

**Biomes in a chunk section**

The biome of each 4×4×4 cell of a chunk section, shown like blocks, at
the cell's lowest corner. Another encoding of the same biomes is network
traffic only, and the order of the palette is not compared. One encoding packs each biome at a bit width that depends
on how many biomes the server listed when the player joined, and the
client reads it at that width whatever width the server names. mscts
compares the biomes the client reads. If the data does not fit that
width, the client reads the rest of the chunk wrong, so that difference
changes what a player sees.

## `level_chunk_with_light.light.sky[]`

**Sky light in a chunk section**

The sky light a server sends for one section of a chunk: a light level
for each block, an empty section, or nothing, which keeps the light the
client already had. Index 0 is the section below the world. A different
level is shown at its position in the world; otherwise each server's
section is described, such as `not sent` or `all 15`. Below the world, an
empty section and a section of level 0 everywhere are the same to the
client, and vanilla itself sends either one, so that difference is not
compared at all. Elsewhere the client later fills an empty section with full sky
light, so the two differ.

## `level_chunk_with_light.light.block[]`

**Block light in a chunk section**

The light from torches and other light sources in one section of a
chunk, compared like sky light. An empty section and a section of level
0 everywhere are the same to the client, so that difference is network
traffic only.

## `level_event`

**World event**

An effect the client plays at a position, such as the particles and sound
of a block breaking. A server that leaves it out shows no effect.

## `level_event.event_id`

**World event type**

Which effect plays. Vanilla sends 2001, a block breaking, with the state of
the broken block as its data. A different number plays a different effect.

## `light_update`

**Light update**

A later change to the light of a chunk. When only one server sent it,
it is shown by the chunk's coordinates, such as `chunk 3 -2`. Light
updates for different chunks can come in any order, but updates for the
same chunk keep their order.

## `light_update.data.sky[]`

**Sky light update**

A later change to the sky light of a chunk section, compared like the
sky light a chunk is sent with.

## `light_update.data.block[]`

**Block light update**

A later change to the block light of a chunk section, compared like the
block light a chunk is sent with.

## `login.enforces_secure_chat`

**Secure chat required**

Whether the server requires signed chat messages. The client tells the
player when a server does not.

## `login.is_flat`

**Flat world flag**

Whether the world is flat. If it is, the client draws the horizon at
the bottom of the world, not at sea level.

## `login.sea_level`

**Sea level**

The world's sea level. In vanilla's flat world it is -63.

## `login_compression.threshold`

**Compression threshold**

The packet size from which the server compresses what it sends. A negative value turns compression off. A different threshold changes network traffic only, not what a player sees.

## `login_finished.profile.username`

**Player name at login**

The name the server gives the player when login finishes. The client shows it as the player's name.

## `login_finished.profile.uuid`

**Player UUID at login**

The player's UUID, which the server sends when the login succeeds. In
offline mode vanilla makes it from the player's name, so a server that
sends another UUID turns the same player into a different one.

## `player_abilities`

**Player abilities**

Whether the player can fly, is flying, takes no damage or builds
instantly, and how fast it flies and walks.

## `player_info_remove.uuids[]`

**Player leaving the list**

The UUID of a player the client takes off its list of players when they
leave. The tab list stops showing them.

## `player_info_update`

**Player list update**

Adds a player to, or changes a player in, the client's list of players:
their name, game mode, latency and whether the tab list shows them.

## `player_info_update.actions[]`

**Player list update part**

Which parts of each player's entry an update sets, such as their name,
game mode or latency. A server that sends other parts sets other things,
or leaves out some that vanilla sets.

## `player_info_update.players[].chat_session`

**Player chat session**

The key a player signs their chat messages with. Offline, vanilla has
none, but still sends this part of the update to say so.

## `player_info_update.players[].display_name`

**Player list display name**

The name the tab list shows in place of the player's own. Vanilla sends
none for a player who just joined, but still sends this part of the
update to say so.

## `player_info_update.players[].name`

**Player name in the list**

The player's name, as the tab list shows it. Players are compared in the
order the server sends them, so a server that sends them in another order
differs here too.

## `player_info_update.players[].uuid`

**Player UUID in the list**

The player's UUID in their player list entry. In offline mode vanilla
makes it from the player's name. A server that makes it another way shows
the same player with another UUID.

## `player_position`

**Player position**

Where the server puts the player, and which way it faces. The client
moves the player there and confirms it.

## `play:post_effects`

**Screen effects**

The screen effects the server applies, as the `/posteffect` command sets
them. At a join vanilla sends none.

## `recipe_book_add`

**Recipes in the recipe book**

Recipes the client adds to the player's recipe book.

## `recipe_book_settings`

**Recipe book settings**

Whether each recipe book is open and filtered.

## `registry_data.entries[]`

**Registry entry**

One entry of a registry the server sends while the player is being configured,
such as one biome or one cow variant. An entry vanilla sends and another
server leaves out is one the client does not have.

## `registry_data.entries[].data`

**Registry entry data**

The contents of a registry entry. Vanilla sends none for an entry that a
data pack both servers share already has, and the client then takes it
from that pack.

## `registry_data.entries[].entry_id`

**Registry entry name**

The name of a registry entry, such as `minecraft:plains`. The client
numbers entries in the order they come, so another order gives other
numbers.

## `registry_data.registry_id`

**Registry name**

Which registry a `registry_data` holds, such as
`minecraft:worldgen/biome`. A difference here usually means the servers
send their registries in a different order.

## `section_blocks_update`

**Block changes in a section**

Many blocks in one chunk section changing at once, as `/fill` and
`/clone` do. A chunk section is a part of a chunk 16 blocks high. The
packet holds the section's position
and a list of changes. Each change has its own test cases, below.

## `section_blocks_update.blocks[]`

**Block change in a section**

One change in the list, or a change only one server sent. mscts compares
the list in the order it is sent. Vanilla sends it in the order of a
hash set, so a server that sends the same changes in another order also
differs here.

## `section_blocks_update.blocks[].state`

**Block state in a section change**

The state a block in the section changes to. A different number shows a
different block or a differently turned one.

## `section_blocks_update.blocks[].x`

**Block x in a section change**

The x coordinate of a changed block, counted from the section's west edge
(0 to 15).

## `section_blocks_update.blocks[].y`

**Block y in a section change**

The y coordinate of a changed block, counted from the section's bottom
(0 to 15).

## `section_blocks_update.blocks[].z`

**Block z in a section change**

The z coordinate of a changed block, counted from the section's north edge
(0 to 15).

## `section_blocks_update.section.y`

**Section height**

Which chunk section the changes are in, counted in sections of 16 blocks
from the world's origin: section -4 holds y from -64 to -49. A different
value puts the same changes at a different height.

## `select_known_packs.known_packs[].id`

**Known pack ID**

The ID of a data pack the server tells the client it has. For each pack the client says it also has, the server leaves out that pack's registry data.

## `select_known_packs.known_packs[].namespace`

**Known pack namespace**

The namespace of a data pack the server tells the client it has, such as `minecraft`.

## `select_known_packs.known_packs[].version`

**Known pack version**

The version of a data pack the server tells the client it has. A pack only counts as known to both when the versions match, so a different version can make the server send registry data it would otherwise leave out.

## `server_data`

**Server description in play**

The server's description and icon, sent again once the player has
joined.

## `set_default_spawn_position`

**World spawn point**

Where the world's spawn point is. The client points compasses at it.

## `remove_entities`

**Entities disappearing**

A packet that tells the client entities are gone, such as the body of a
player who left. A server that leaves it out leaves the entity in the
world.

## `remove_entities.entity_ids[]`

**Entity disappearing**

One entity the client removes. A player is named by their UUID.

## `set_entity_data`

**Entity data**

The data of an entity, such as which item a dropped item holds and how many.
A different value shows the player a different item or count.

## `set_entity_data.entries[].index`

**Entity data field**

Which of an entity's data fields an entry sets, such as a player's health.

## `set_entity_data.entries[].serializer`

**Entity data type**

The type of the value an entity data entry holds. Each field has one
type, so a different type usually comes with a different field.

## `set_entity_data.entries[].value`

**Entity data value**

The value an entity data entry sets, such as a player's health.

## `set_entity_motion`

**Entity velocity**

How fast and in which direction an entity moves. The client moves the
entity with it until the next update.

## `set_experience`

**Experience**

The player's experience bar, level and total experience.

## `set_health`

**Health and food**

The player's health, food level and saturation.

## `set_held_slot`

**Selected hotbar slot**

Which hotbar slot the player is holding.

## `status_response.description`

**Server list description**

The server's description in the multiplayer server list. This test case
compares it in its original format. Vanilla's `"mscts"` and Pumpkin's
`{"text": "mscts"}` display the same text, so that difference is network
traffic only. Differences in the text the client reads are compared below.

## `status_response.description.text`

**Server list description text**

The description text, after mscts rewrites equivalent text components
into one form. A different value changes the description a player reads in the
server list.

## `status_response.enforceSecureChat`

**Unused secure chat flag**

Pumpkin sends this key without the `s` in vanilla's `enforcesSecureChat`.
The vanilla client never reads it, so its presence changes only network
traffic. It does not change what a player sees or how secure chat is read.

## `status_response.favicon`

**Server list icon**

The icon shown beside the server in the multiplayer list. A different
icon changes what a player sees. An omitted key and `null` both mean no
icon to the vanilla client; that difference is network traffic only.

## `status_response.players.max`

**Player limit**

The maximum player count the server advertises. A different value changes
the player limit shown in the multiplayer list; it does not by itself
prove the server enforces that limit when a player joins.

## `status_response.players.online`

**Online players**

The current player count the server advertises. A different value changes
the online count shown beside the player limit in the server list.

## `status_response.players.sample`

**Server list player sample**

The sample of players whose names appear when a player hovers over the
server's player count. An omitted sample and an empty list both show no
names, so that difference is network traffic only. A nonempty sample's
fields have their own test case names, such as
`status_response.players.sample[].name`.

## `status_response.players.sample[].id`

**Server list player UUID**

The UUID the server lists for a player in the sample. The client and other
tools use it to tell players apart, so a server that derives offline UUIDs
differently lists another one for the same name. It is the same UUID as in
`login_finished.profile.uuid`.

## `status_response.players.sample[].name`

**Server list player name**

The name the server lists for a player in the sample, shown when a player hovers over the server's player count.

## `status_response.version.name`

**Server version name**

The version name the server advertises, such as `26.3`. A different name
changes the version text the client can show for an incompatible server.
It is separate from the protocol number that determines compatibility.

## `status_response.version.protocol`

**Protocol version**

The protocol number the server advertises. A different value can make the
client show the server as incompatible. The Target's protocol number is
777. This test case checks the advertised value, not every packet layout.

## `status:pong_response.timestamp`

**Server list ping response**

The value returned for a server list ping. The server should echo what
the client sent. A different value breaks that exchange. The time until
the answer arrives is measured separately, as `status.rtt`. The `status:`
prefix distinguishes this packet from a pong in another protocol state.

## `system_chat`

**Chat message from the server**

A message the server shows in the chat, such as the answer to a command.
A server that leaves it out, or sends an extra one, shows the player
different messages from vanilla. mscts keeps the order of the packets in
a window. If a server sends a command's answer after the block changes
the command makes, where vanilla sends it before them, the answer is
reported as left out in one place and sent in another.

## `system_chat.content`

**Chat message text**

The message's text component. mscts compares its bytes, so the same
message written another way also differs here. The translation key in the
bytes, such as `commands.setblock.success`, says what the message is.

## `ticking_state`

**Tick rate and freeze state**

How many times a second the server ticks, and whether `/tick freeze` has
stopped it. The client ticks at that rate too.

## `ticking_step`

**Tick steps**

How many ticks `/tick step` has left to run while the game is frozen.

## `update_advancements`

**Advancements**

The advancements the player can see and how far they have got with each.

## `update_attributes`

**Entity attributes**

An entity's attributes, such as its movement speed or how far a player
can reach, with their modifiers.

## `update_enabled_features.feature_flags[]`

**Enabled feature flag**

A feature flag the server enables, such as `minecraft:vanilla`. Flags switch sets of game features on, so a different set changes what the client lets a player use.

## `update_recipes`

**Recipe data**

What the client needs to show recipes: the sets of items some recipe
screens accept, and the stonecutter's recipes.

## `configuration:update_tags.tagged_registries[].tags[]`

**Tag**

One tag the server sends, such as `minecraft:logs`: a named list of
blocks, items or other entries that recipes, block behaviour and
commands refer to.

## `configuration:update_tags.tagged_registries[].tags[].entries[]`

**Tag member**

One entry of a tag, by its number in its registry.

## `configuration:update_tags.tagged_registries[].tags[].tag_name`

**Tag name**

The name of a tag, such as `minecraft:logs`.
