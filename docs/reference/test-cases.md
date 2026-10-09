# Test case reference

Search the name from a Report to find what mscts compared and what a
difference means. A test case without an entry is still reported by name.
A test case that mscts never compares, such as
`container_set_slot.state_id`, is listed only when the two servers differ
in it, and is [not scored](/guide/reading-a-report#network-traffic-differences).
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

## `container_close`

**Window closing**

The server closing the window the player has open, such as a chest. A
server that leaves it out keeps the window open.

## `container_close.window_id`

**Window to close**

The number of the window the server closes, where 0 is the player's own
inventory.

## `container_set_content`

**Inventory contents**

Every slot of the container the player has open. At a join, this is the
player's own inventory.

## `container_set_content.carried_item`

**Item on the cursor**

The item stack the cursor holds when the contents are sent, with its
count and components. A difference changes what the player is holding
with the mouse.

## `container_set_content.carried_item.count`

**Cursor item count**

How many items the stack on the cursor holds. A difference gives the
player another amount.

## `container_set_content.carried_item.item`

**Cursor item type**

The kind of item the stack on the cursor holds, given as its number in
the item registry. A different number is a different item.

## `container_set_content.carried_item.components.added`

**Cursor item components**

The components the stack on the cursor has on top of what its item has
by default. A stack with none is compared as this empty list.

## `container_set_content.carried_item.components.added[]`

**Cursor item component**

One component the stack on the cursor has on top of what its item has by
default, compared whole when only one server sends it. A difference adds
a component or leaves one out.

## `container_set_content.carried_item.components.added[].type`

**Cursor item component name**

The name of a component the stack on the cursor has on top of what its
item has by default, such as `minecraft:damage`. A difference adds
another component or leaves one out.

## `container_set_content.carried_item.components.added[].value`

**Cursor item component data**

What a component added to the stack on the cursor holds, such as how
damaged the item is. A difference changes that part of the item.

## `container_set_content.carried_item.components.removed`

**Cursor item removed components**

The components of the item that the stack on the cursor takes away. A
stack that takes none away is compared as this empty list.

## `container_set_content.carried_item.components.removed[]`

**Cursor item removed component**

The name of a component the item has by default and the stack on the
cursor takes away. A difference keeps or removes another default.

## `container_set_content.slot_data`

**Inventory slot items**

Every slot of the window, in slot order. A window with no slots is
compared as this empty list.

## `container_set_content.slot_data[]`

**Inventory slot item**

The item stack in one slot, listed in slot order, with its count and
components. A difference puts another item, another amount or other
components in that slot.

## `container_set_content.slot_data[].count`

**Slot item count**

How many items the stack in a slot holds. A difference gives the player
another amount.

## `container_set_content.slot_data[].item`

**Slot item type**

The kind of item the stack in a slot holds, given as its number in the
item registry. A different number is a different item.

## `container_set_content.slot_data[].components.added`

**Slot item components**

The components the stack in a slot has on top of what its item has by
default. A stack with none is compared as this empty list.

## `container_set_content.slot_data[].components.added[]`

**Slot item component**

One component the stack in a slot has on top of what its item has by
default, compared whole when only one server sends it. A difference adds
a component or leaves one out.

## `container_set_content.slot_data[].components.added[].type`

**Slot item component name**

The name of a component the stack in a slot has on top of what its item
has by default, such as `minecraft:damage`. A difference adds another
component or leaves one out.

## `container_set_content.slot_data[].components.added[].value`

**Slot item component data**

What a component added to the stack in a slot holds, such as how damaged
the item is. A difference changes that part of the item.

## `container_set_content.slot_data[].components.removed`

**Slot item removed components**

The components of the item that the stack in a slot takes away. A stack
that takes none away is compared as this empty list.

## `container_set_content.slot_data[].components.removed[]`

**Slot item removed component**

The name of a component the item has by default and the stack in a slot
takes away. A difference keeps or removes another default.

## `container_set_content.state_id`

**Inventory state number**

The number the server gives to this version of the window's contents.
The client keeps it and sends it back with its next click, which lets
the server tell whether the click was made on contents that have changed
since. The player sees nothing of it, so a different number is network
traffic only.

## `container_set_content.window_id`

**Inventory window**

The window the contents are for, where 0 is the player's own inventory.
The client ignores contents for a window that is not the one open, so a
difference can leave the slots unchanged.

## `container_set_data`

**Window property**

One number a window shows besides its items, such as how far a furnace
has smelted. A server that leaves it out, or sends another, shows a
different progress or setting.

## `container_set_data.property`

**Window property number**

Which number of the window is set. Each kind of window numbers its own,
so the same value means something else in a furnace and in an enchanting
table.

## `container_set_data.value`

**Window property value**

The value the window's number is set to.

## `container_set_data.window_id`

**Window of a property**

The window the number belongs to. The client ignores it for a window
that is not the one open.

## `container_set_slot`

**Inventory slot change**

One slot of a window changing, such as the item a player picks up. A
server that leaves it out, or sends another, shows a different item in
that slot.

## `container_set_slot.slot`

**Inventory slot number**

The number of the slot that changes. Slots are numbered from 0 in the
order the window lists them, so a different number changes another slot.

## `container_set_slot.slot_data`

**Item in a changed slot**

The item stack the slot holds after the change, with its count and
components. An empty slot is sent as no stack.

## `container_set_slot.slot_data.count`

**Changed slot item count**

How many items the stack in the changed slot holds. A difference gives
the player another amount.

## `container_set_slot.slot_data.item`

**Changed slot item type**

The kind of item the stack in the changed slot holds, given as its
number in the item registry. A different number is a different item.

## `container_set_slot.slot_data.components.added`

**Changed slot item components**

The components the stack in the changed slot has on top of what its item
has by default. A stack with none is compared as this empty list.

## `container_set_slot.slot_data.components.added[]`

**Changed slot item component**

One component the stack in the changed slot has on top of what its item
has by default, compared whole when only one server sends it. A
difference adds a component or leaves one out.

## `container_set_slot.slot_data.components.added[].type`

**Changed slot item component name**

The name of a component the stack in the changed slot has on top of what
its item has by default, such as `minecraft:damage`. A difference adds
another component or leaves one out.

## `container_set_slot.slot_data.components.added[].value`

**Changed slot item component data**

What a component added to the stack in the changed slot holds, such as
how damaged the item is. A difference changes that part of the item.

## `container_set_slot.slot_data.components.removed`

**Changed slot item removed components**

The components of the item that the stack in the changed slot takes
away. A stack that takes none away is compared as this empty list.

## `container_set_slot.slot_data.components.removed[]`

**Changed slot item removed component**

The name of a component the item has by default and the stack in the
changed slot takes away. A difference keeps or removes another default.

## `container_set_slot.state_id`

**Inventory slot change state number**

The number the server gives to this version of the window's contents.
The client keeps it and sends it back with its next click. The player
sees nothing of it, so a different number is network traffic only.

## `container_set_slot.window_id`

**Window of a slot change**

The window the slot is in, where 0 is the player's own inventory. For
any other window, the client ignores a change unless that window is the
one open.

## `mount_screen_open`

**Mount inventory opening**

The inventory of a mount, such as a horse, opening as a window. A server
that leaves it out does not show the player the mount's inventory.

## `mount_screen_open.entity_id`

**Mount whose inventory opens**

The mount whose inventory opens. mscts compares the entity each server
refers to, rather than its server-assigned number. A difference opens
another mount's inventory.

## `mount_screen_open.inventory_columns`

**Mount chest columns**

How many columns of chest slots the mount has, or 0 for none. A
different number shows a different number of slots.

## `mount_screen_open.window_id`

**Mount inventory window**

The number the server gives to the window it opens.

## `open_screen`

**Window opening**

The server opening a window for the player, such as a chest or a
furnace. A server that leaves it out, or opens another kind, shows the
player another screen.

## `open_screen.window_id`

**Opened window number**

The number the server gives to the window. The client sends it back in
its clicks and when it closes the window.

## `open_screen.window_title`

**Opened window title**

The text the window shows as its title, such as `Chest`. A different
text shows another title.

## `open_screen.window_type`

**Opened window type**

The kind of window, as its number in the menu registry. It decides which
screen the client draws, so a different number draws a different one.

## `set_cursor_item`

**Cursor item change**

The server changing the stack the cursor holds. A server that leaves it
out leaves the cursor as it was.

## `set_cursor_item.slot_data`

**New cursor item**

The stack the cursor holds after the change, with its count and
components. An empty cursor is sent as no stack.

## `set_cursor_item.slot_data.count`

**New cursor item count**

How many items the new stack on the cursor holds. A difference gives the
player another amount.

## `set_cursor_item.slot_data.item`

**New cursor item type**

The kind of item the new stack on the cursor holds, given as its number
in the item registry. A different number is a different item.

## `set_cursor_item.slot_data.components.added`

**New cursor item components**

The components the new stack on the cursor has on top of what its item
has by default. A stack with none is compared as this empty list.

## `set_cursor_item.slot_data.components.added[]`

**New cursor item component**

One component the new stack on the cursor has on top of what its item
has by default, compared whole when only one server sends it. A
difference adds a component or leaves one out.

## `set_cursor_item.slot_data.components.added[].type`

**New cursor item component name**

The name of a component the new stack on the cursor has on top of what
its item has by default, such as `minecraft:damage`. A difference adds
another component or leaves one out.

## `set_cursor_item.slot_data.components.added[].value`

**New cursor item component data**

What a component added to the new stack on the cursor holds, such as how
damaged the item is. A difference changes that part of the item.

## `set_cursor_item.slot_data.components.removed`

**New cursor item removed components**

The components of the item that the new stack on the cursor takes away.
A stack that takes none away is compared as this empty list.

## `set_cursor_item.slot_data.components.removed[]`

**New cursor item removed component**

The name of a component the item has by default and the new stack on the
cursor takes away. A difference keeps or removes another default.

## `set_player_inventory`

**Player inventory slot change**

One slot of the player's own inventory changing, whichever window is
open. A server that leaves it out, or sends another, shows a different
item there.

## `set_player_inventory.slot`

**Player inventory slot number**

The number of the inventory slot that changes: 0 to 8 are the hotbar, 9
to 35 the rest of the inventory, 36 to 39 the armor, 40 the off hand,
41 the body and 42 the saddle.

## `set_player_inventory.slot_data`

**Item in a player inventory slot**

The item stack the slot holds after the change, with its count and
components. An empty slot is sent as no stack.

## `set_player_inventory.slot_data.count`

**Inventory item count**

How many items the stack in the player's slot holds. A difference gives
the player another amount.

## `set_player_inventory.slot_data.item`

**Inventory item type**

The kind of item the stack in the player's slot holds, given as its
number in the item registry. A different number is a different item.

## `set_player_inventory.slot_data.components.added`

**Inventory item components**

The components the stack in the player's slot has on top of what its
item has by default. A stack with none is compared as this empty list.

## `set_player_inventory.slot_data.components.added[]`

**Inventory item component**

One component the stack in the player's slot has on top of what its item
has by default, compared whole when only one server sends it. A
difference adds a component or leaves one out.

## `set_player_inventory.slot_data.components.added[].type`

**Inventory item component name**

The name of a component the stack in the player's slot has on top of
what its item has by default, such as `minecraft:damage`. A difference
adds another component or leaves one out.

## `set_player_inventory.slot_data.components.added[].value`

**Inventory item component data**

What a component added to the stack in the player's slot holds, such as
how damaged the item is. A difference changes that part of the item.

## `set_player_inventory.slot_data.components.removed`

**Inventory item removed components**

The components of the item that the stack in the player's slot takes
away. A stack that takes none away is compared as this empty list.

## `set_player_inventory.slot_data.components.removed[]`

**Inventory item removed component**

The name of a component the item has by default and the stack in the
player's slot takes away. A difference keeps or removes another default.

## `configuration:custom_payload.data`

**Configuration plugin message data**

The data of a plugin message sent while the player is being configured.
Vanilla sends one on the `minecraft:brand` channel. It holds the
server's name, which the client shows on its debug screen.

## `disguised_chat`

**Disguised chat message**

A player's message that the server shows as from the player but sends
as text, with no place for a signature, such as `/say` sent unsigned.
Vanilla sends `player_chat` for a message from a player with no chat
session, and for a command such as `/say` sent the way the client sends
it. A server that sends this packet instead is reported here and under
`player_chat`.

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

## `player_chat`

**Chat message from a player**

A message a player said, or sent with a command such as `/msg`. Vanilla
sends it to every player who can see the message, the sender included.
Its time is taken from the server's clock, so mscts does not compare it.
Each other field has its own test case, below.

## `player_chat.chat_type.reference`

**Chat message type**

Which entry of the `minecraft:chat_type` registry the client uses to
show the message, such as `minecraft:chat` for a plain message or
`minecraft:msg_command_incoming` for a whisper.

## `player_chat.filter.bits`

**Filtered characters in a chat message**

Which characters the server hid from the message, when it filters only
part of it. Vanilla filters nothing unless a text filter is set up.

## `player_chat.filter.type`

**Chat message filtering**

Whether the server let the message through, hid all of it, or hid some
characters.

## `player_chat.global_index`

**Chat message count**

How many player messages the server has sent this player before this
one. A server that counts from another number, or skips one, differs
here on every later message.

## `player_chat.index`

**Sender's chat message count**

How many messages the sender had sent in its chat session before this
one. A player with no chat session has none, so vanilla sends 0.

## `player_chat.message`

**Chat message text from a player**

What the player said, as plain text.

## `player_chat.previous_messages`

**Earlier chat messages a signature covers**

The earlier messages the sender had seen when it signed this one. An
unsigned message has none.

## `player_chat.salt`

**Chat message salt**

The random number the sender signed with the message. Vanilla sends 0
for an unsigned message.

## `player_chat.sender`

**Chat message sender**

The UUID of the player who sent the message.

## `player_chat.sender_name`

**Chat message sender name**

The name the client shows for the sender, as a text component.
mscts compares its bytes, so the same name written another way also
differs here.

## `player_chat.signature`

**Chat message signature**

The sender's signature of the message. An unsigned message has none.

## `player_chat.target_name`

**Chat message recipient name**

The name of the player or team a message was sent to, such as the
player named in `/msg`, or nothing for a message to everyone.

## `player_chat.unsigned_content`

**Chat message text the server changed**

Text the client shows in place of the signed message. Vanilla sends
none unless something changed what the player said.

## `player_info_remove`

**Player list removal**

Removes players from the client's list of players, as when a player
leaves the server.

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

## `player_position.flags`

**Relative player position parts**

Which parts of the position and rotation the client adds to its own,
rather than takes as they are. When vanilla sends a player back it sets
none, so the client takes the whole position as given.

## `player_position.pitch`

**Player pitch**

How far up or down the server makes the player look, in degrees.

## `player_position.teleport_id`

**Teleport number**

The number the client sends back to confirm a teleport. The server
counts its teleports of the player up from 1, so a different number
means one server sent the player back, or teleported it, more often
than the other.

## `player_position.velocity_x`

**Player velocity x**

The player's speed along x after the teleport. When vanilla sends a
player back it sends 0, so the player stops.

## `player_position.velocity_y`

**Player velocity y**

The player's speed along y after the teleport. When vanilla sends a
player back it sends 0, so the player stops.

## `player_position.velocity_z`

**Player velocity z**

The player's speed along z after the teleport. When vanilla sends a
player back it sends 0, so the player stops.

## `player_position.x`

**Player position x**

The x coordinate the server puts the player at. When the server refuses
a move, it is where the server still has the player.

## `player_position.y`

**Player position y**

The y coordinate the server puts the player at, the height of its feet.

## `player_position.yaw`

**Player yaw**

Which way the server turns the player, in degrees.

## `player_position.z`

**Player position z**

The z coordinate the server puts the player at.

## `play:disconnect`

**Kick**

The server ends the player's connection, as vanilla does to a survival
player that floats in the air for too long. A server that leaves it out
lets the player stay; one that sends it where vanilla doesn't kicks a
player vanilla would keep.

## `play:disconnect.reason`

**Kick reason**

The message the client shows a kicked player, such as "Flying is not
enabled on this server", or `multiplayer.disconnect.illegal_characters`
for a chat message with a `§`.

For a chat message longer than 256 characters, vanilla's reason is the
text of the Java exception it got reading the message: `Internal
Exception: io.netty.handler.codec.DecoderException: Failed to decode
packet 'serverbound/minecraft:chat'`. A server that kicks the player
too still differs here unless it sends the same text.

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

The contents of a registry entry. Vanilla sends none for an entry in a data
pack that the server and the client both have at the same version, and
the client then takes it from that pack.

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

## `set_chunk_cache_center`

**View centre**

The chunk the player's view is centred on. The client keeps only the
chunks within its view distance plus three chunks of it, and drops a
chunk sent outside that area. A server that leaves it out, or sends it
at another point, can leave the player with holes in the world.

## `set_chunk_cache_center.chunk_x`

**View centre chunk x**

The x coordinate of the chunk the player's view is centred on.

## `set_chunk_cache_center.chunk_z`

**View centre chunk z**

The z coordinate of the chunk the player's view is centred on.

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

Pumpkin sends this key without the `s` that vanilla's `enforcesSecureChat` has.
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

## `system_chat.overlay`

**Whether a message shows above the hotbar**

Whether the client shows the message above the hotbar instead of in the
chat.

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

## `commands.nodes[].properties.behavior`

**Command string argument behaviour**

Whether a string argument takes one word, a quoted phrase, or the rest of
the line. A difference changes how the client reads and checks the command a
player types.

## `commands.nodes[].properties.flags`

**Command argument flags**

Settings whose meaning depends on the argument type. For a number they say
whether a minimum or maximum is sent; for an entity they say whether it must
be one entity or players only. A difference changes which arguments the
client accepts.

## `commands.nodes[].properties.max`

**Command argument maximum**

The largest value a number argument accepts, or no explicit maximum. A
difference changes which numbers the client marks as valid while a player
types a command.

## `commands.nodes[].properties.min`

**Command argument minimum**

The smallest value an argument accepts, or no explicit minimum. For a time
argument it is counted in ticks. A difference changes which values the
client marks as valid while a player types a command.

## `commands.root_index`

**Command tree root**

The position of the root in the list of command nodes. The client starts
reading commands there. Another position can name the same root if the
server lists its nodes in another order; a position that names another node
changes the commands the client understands.

## `entity_event.entity_id`

**Entity receiving an event**

Which entity receives an event, such as a hurt animation. mscts compares the
entity each server refers to, rather than its server-assigned number. A
difference applies the effect to another entity.

## `entity_event.event_id`

**Entity event type**

Which event the client applies to the entity. Its meaning depends on the
entity type, such as a hurt animation for a living entity. A difference can
play another effect or none.

## `game_event.event`

**Game event type**

Which change of game state the client applies. At a join this can tell the
client to wait for the chunks around the player. Another event can change
the game mode, weather or another part of the client state instead.

## `game_event.value`

**Game event value**

The value carried by a game event, whose meaning depends on the event type.
For a game mode change it selects the mode; for a rain level change it sets
the strength. Some events ignore the value, so a difference does not always
change what a player sees.

## `level_chunk_with_light.chunk_x`

**Chunk x**

The chunk's x coordinate, counted in chunks of 16 blocks. A difference puts
the chunk at another position east or west. Chunks are paired by position,
so a chunk at another position can also be reported as missing or
unexpected.

## `level_chunk_with_light.chunk_z`

**Chunk z**

The chunk's z coordinate, counted in chunks of 16 blocks. A difference puts
the chunk at another position south or north. Chunks are paired by position,
so a chunk at another position can also be reported as missing or
unexpected.

## `level_chunk_with_light.heightmaps[].data[]`

**Chunk heightmap data**

One packed value in a heightmap, which records the heights of block columns.
A difference can give the client other heights for its surface queries, even
when the chunk contains the same blocks. The kind of surface is set by the
heightmap type.

## `level_chunk_with_light.heightmaps[].type`

**Chunk heightmap type**

Which kind of surface a heightmap records, such as the highest non-air block
or the highest block that stops movement. mscts compares the types the
client reads and sorts heightmaps by those types. A difference changes which
surface the client can look up.

## `level_chunk_with_light.sections[].block_count`

**Non-air blocks in a chunk section**

The number of non-air blocks in one chunk section. The client uses a zero
count to treat a section as empty. A wrong zero can hide blocks even when
their states are sent; another nonzero count does not by itself change those
states.

## `level_chunk_with_light.sections[].fluid_count`

**Fluid blocks in a chunk section**

The number of positions in a chunk section that contain fluid, including
waterlogged blocks. The client uses the count to tell whether the section
has fluid. A wrong zero can make it treat a section containing fluid as
having none.

## `login.death_location`

**Last death location**

The dimension and block position of the player's last death, or no recorded
death. A recovery compass uses it to point to that location. A difference
can point the compass elsewhere or leave it without a location.

## `login.dimension_name`

**Joined dimension**

The name of the dimension the player joins, such as `minecraft:overworld`. The
client uses it as the identity of its world. Another name can change whether
a saved location, such as the last death position, belongs to that world.

## `login.dimension_names[]`

**Available dimension name**

One dimension name the server advertises at join. The client uses the list
in dimension suggestions for commands. A difference changes those
suggestions; the list alone does not show whether the server can move a
player to each dimension.

## `login.dimension_type`

**Joined dimension type**

The joined dimension's type, by its entry in the dimension type registry.
That entry sets properties such as the world's height, sky and ambient
light. A difference can make the client display the same world with other
properties.

## `login.do_limited_crafting`

**Limited crafting**

Whether crafting is limited to recipes the player has unlocked. The client
keeps this rule when showing available recipes, so a difference can make it
offer recipes the server does not allow, or hide ones it allows.

## `login.enable_respawn_screen`

**Death screen enabled**

Whether the client shows the death screen when the player dies. A difference
changes whether the player sees that screen or immediately asks to respawn.

## `login.entity_id`

**Player entity at join**

The entity id the client assigns to its own player. mscts gives
corresponding entities the same names before comparing them, so another
server-assigned number alone does not differ here. A wrong reference in a
later packet can apply a change to another entity.

## `login.game_mode`

**Game mode at join**

The player's game mode, such as survival or creative. The client uses it for
controls and screens, so a difference changes how the player can interact
with the world.

## `login.hashed_seed`

**Biome seed**

The hashed seed the client uses to choose a biome near the edges of biome
cells. A difference can move the boundaries of biome colours and effects
even when the chunk supplies the same biomes. This is not the world
generation seed.

## `login.is_debug`

**Debug world flag**

Whether the joined world is a debug world. The client treats block states
specially in that world. A difference can change the blocks it reads and
displays even when the same chunk data arrives.

## `login.is_hardcore`

**Hardcore world flag**

Whether the world is hardcore. The client changes its health icons and death
screen for hardcore, so a difference changes what the player sees there.

## `login.max_players`

**Player limit at join**

The maximum player count carried by the join packet. The 26.3 client
does not read this field when handling the packet, so a different value
here does not by itself change what a player sees. The player limit
advertised in the server list is compared separately.

## `login.online_mode`

**Online mode at join**

Whether the server declares online mode in the join packet. When true, the
client prepares its key pair for signed chat. A difference changes that chat
setup; this flag alone does not prove the server authenticated the player at
login.

## `login.portal_cooldown`

**Portal cooldown at join**

How many ticks remain before the player can use a portal again. The client
stores this on the player, so a difference changes when it considers the
cooldown over.

## `login.previous_game_mode`

**Previous game mode**

The player's previous game mode, or none. The client remembers it when
switching modes, so a difference can change which mode it offers to return
to.

## `login.reduced_debug_info`

**Reduced debug information**

Whether the client hides some debug information, including the player's
exact coordinates. A difference changes the information available on the
debug screen.

## `login.simulation_distance`

**Simulation distance at join**

The server's simulation distance in chunks. The client uses it to decide how
far from the player entities should tick. A difference can change local
entity motion even within the chunks the client can see.

## `login.view_distance`

**View distance at join**

The server's view distance in chunks. The client uses it to size its chunk
cache and limit rendering alongside the player's own setting. A difference
can change how much of the world it keeps and displays.

## `set_entity_data.entity_id`

**Entity receiving data**

Which entity the following data updates. mscts compares corresponding
entities rather than their server-assigned numbers. A difference applies the
data to another entity, changing its appearance or state instead.

## `set_experience.experience_bar`

**Experience bar progress**

How full the player's experience bar is, from 0 to 1. A difference changes
the fill of the bar shown above the hotbar.

## `set_experience.level`

**Experience level**

The player's experience level. A difference changes the number above the
hotbar and the client's checks of whether the player has enough levels for
an enchantment.

## `set_experience.total_experience`

**Total experience points**

The player's total experience points, which the client stores alongside the
bar and level. The ordinary experience display uses the other two fields, so
a difference here alone need not change that display.

## `set_health.food`

**Food level**

The player's food level, normally from 0 to 20. A difference changes the
hunger icons and can change whether the client lets the player start
sprinting.

## `set_health.health`

**Health**

The player's health in health points, with two points per heart. A
difference changes the hearts shown and can make the client treat the player
as dead.

## `set_health.saturation`

**Food saturation**

The player's food saturation, the reserve used before the food level falls.
The client also uses zero saturation when drawing the hunger icons. A
difference can change their animation even when the food level is the same.

## `update_advancements.advancements[].display`

**Advancement display**

An advancement's title, description, icon, frame and display flags, or no
display. A difference can change its entry in the advancement screen or its
completion toast; an advancement without a display has no entry of its own.

## `update_advancements.advancements[].id`

**Advancement id**

The name that identifies an advancement. The client uses it to connect
progress and parent references to that advancement. A difference can leave
those references pointing to another advancement or to none.

## `update_advancements.advancements[].parent_id`

**Advancement parent**

The id of an advancement's parent, or none for a root. A difference changes
where it belongs in the advancement tree and which entry it connects to on
the screen.

## `update_advancements.advancements[].requirements[][]`

**Advancement requirements**

The criteria required to complete an advancement. Each inner list offers
alternatives; at least one criterion in each list must be met. A difference
changes when the client considers the advancement complete and how it shows
progress.

## `update_advancements.advancements[].sends_telemetry_data`

**Advancement telemetry flag**

Whether the advancement is marked for telemetry when completed. A difference
changes whether the client can report its completion, subject to the
player's telemetry settings. It does not by itself change the advancement's
display or requirements.

## `update_advancements.advancements[].x`

**Advancement x position**

The advancement's horizontal position in its tree. A difference moves its
entry on the advancement screen when it has a display.

## `update_advancements.advancements[].y`

**Advancement y position**

The advancement's vertical position in its tree. A difference moves its
entry on the advancement screen when it has a display.

## `update_advancements.progress[].criteria[].criterion`

**Advancement progress criterion**

The name of a criterion whose completion state is updated. A difference
applies that progress to another requirement and can change how much of the
advancement the client considers complete.

## `update_advancements.progress[].id`

**Advancement receiving progress**

The id of the advancement whose progress is updated. A difference can give
another advancement that progress or leave it unapplied if the client does
not know the id.

## `update_advancements.reset`

**Advancement reset**

Whether the client clears its existing advancements before applying this
update. A difference can leave old entries on the advancement screen or
remove entries the server expected to keep.

## `update_advancements.show_advancements`

**Advancement notifications enabled**

Whether this update allows notifications for completed advancements. A
difference can show or suppress completion toasts while the advancement
progress itself stays the same.

## `update_attributes.attributes[].attribute`

**Entity attribute name**

Which attribute an entry updates, such as movement speed or interaction
reach. A difference changes which property the client applies the base value
and modifiers to.

## `update_attributes.attributes[].base`

**Entity attribute base value**

The base value of an entity attribute before modifiers are applied. A
difference can change the resulting value, such as how fast an entity moves
or how far a player can reach.

## `update_attributes.entity_id`

**Entity receiving attributes**

Which entity receives an attribute update. mscts compares corresponding
entities rather than their server-assigned numbers. A difference applies
properties such as speed or reach to another entity.

## `update_recipes.property_sets[].items[]`

**Recipe input item**

One item in a recipe property set, by its item registry id. These sets tell
the client which items some recipe slots accept. A difference can change
whether a screen accepts an item in a slot.

## `update_recipes.property_sets[].property_set_id`

**Recipe property set name**

Which recipe property set the following items belong to, such as the
furnace's inputs. A difference can associate the same items with another
kind of recipe slot.

## `update_recipes.stonecutter_recipes[].ingredients.ids[]`

**Stonecutter input item**

One item registry id in the explicit list of ingredients for a stonecutter
recipe. A difference can make the client offer that recipe for another input
item or leave it out for an item it should accept.

## `update_recipes.stonecutter_recipes[].slot_display.type`

**Stonecutter result display type**

How the client reads and draws a stonecutter recipe's result, such as a
single item or an item stack. A difference can change the result shown on
the recipe button.

## `update_recipes.stonecutter_recipes[].slot_display.value.count`

**Stonecutter result count**

The item count in an item stack shown for a stonecutter recipe. A difference
changes the quantity the client displays; it does not by itself prove which
items the server gives when crafting.

## `update_recipes.stonecutter_recipes[].slot_display.value.item`

**Stonecutter result item**

The item registry id in an item stack shown for a stonecutter recipe. A
difference changes the item the client displays on that recipe's button.

## `player_info_update.players[].game_mode`

**Player game mode in the list**

The game mode stored for a player in the client. Spectators are drawn
differently in the player list and sorted after other players with the same
list priority. A difference can change that display. An update for the
client's own player also changes how it handles the game mode.

## `player_info_update.players[].hat_visible`

**Player hat in the list**

Whether the player's skin hat layer is shown over its head in the player
list. A difference can show or hide that layer when the list draws heads.

## `player_info_update.players[].listed`

**Player shown in the list**

Whether the player belongs in the list shown by the Tab key. A difference
can add or remove that entry while the player remains known to the client.
The list's display limit can still keep an entry off the screen.

## `player_info_update.players[].ping`

**Player connection delay in the list**

The player's reported connection delay in milliseconds. The client uses it
to choose the connection icon in the player list. A difference can change
that icon; it does not by itself change the actual connection delay.

## `player_info_update.players[].priority`

**Player list order**

The priority used to sort players in the player list. Higher values come
first, before the game mode, team and name decide the order of ties. A
difference can move an entry in that list.

## `set_held_slot.slot`

**Selected hotbar slot number**

The hotbar slot the client selects, numbered 0 to 8. A difference can make
the player hold another item. Values outside that range are ignored by the
26.3 client.

## `add_entity.data`

**Entity spawn data**

A number some entities need to appear correctly. It means different things for different kinds of entity.

## `add_entity.entity_id`

**Entity number**

The number later packets use to refer to the entity. mscts compares entities by their type and where they appear, so two servers numbering them differently is not a difference by itself.

## `add_entity.head_yaw`

**Entity head direction**

The way the entity's head turns, as an angle. A difference turns the entity's head.

## `add_entity.pitch`

**Entity up-down angle**

How far up or down the entity looks, as an angle. A difference tilts the entity.

## `add_entity.type`

**Entity type**

Which kind of entity appears, such as a dropped item or a pig. A different type shows a different entity.

## `add_entity.velocity.scale`

**Entity motion scale**

The size of the unit the entity's starting speed is counted in. A difference changes how fast it starts to move.

## `add_entity.velocity.y`

**Entity upward speed**

How fast the entity starts to move up or down. A block's drop pops up at the same speed on vanilla every time, so a difference shows an item that jumps higher or lower.

## `block_changed_ack`

**Block action acknowledgement**

The server telling the player it has dealt with a block action the client guessed at, such as breaking or placing a block. Without it the client keeps showing its guess.

## `block_changed_ack.sequence`

**Acknowledged action number**

Which of the client's guessed actions the server acknowledges. The client keeps its guess until it hears that action's number, so a wrong number leaves a block looking changed or changes it back too soon.

## `level_event.data`

**World event data**

Extra detail for the effect. For a block breaking it is the state of the broken block, which picks the particles and the sound.

## `level_event.global_event`

**World event heard everywhere**

Whether every player hears the effect however far away they are, or only the players near it. Block effects are only for those near.

## `level_event.pos.x`

**World event x**

The x coordinate where the effect plays. A different value plays it somewhere else.

## `level_event.pos.y`

**World event y**

The y coordinate where the effect plays. A different value plays it somewhere else.

## `level_event.pos.z`

**World event z**

The z coordinate where the effect plays. A different value plays it somewhere else.

## `set_entity_data.entries[].value.count`

**Item count in entity data**

How many items are in the stack an entity holds, such as a dropped item. A different count shows a different stack on the ground.

## `set_entity_data.entries[].value.item`

**Item type in entity data**

Which item is in the stack an entity holds, such as a dropped item. A different item drops something else.
## `damage_event`

**Damage taken**

A packet that tells the client an entity took damage. The client plays the hurt effect from it. A server that leaves it out, or sends it for another entity, shows no hit, or a hit on the wrong target.

## `damage_event.entity_id`

**Entity taking damage**

Which entity took the damage. mscts compares the entity each server refers to, rather than its server-assigned number.

## `damage_event.source_type`

**Damage type**

The kind of damage, such as a player's attack. The client uses it to choose the hurt sound and the death message.

## `damage_event.source_cause_id`

**Entity that caused the damage**

The entity that started the damage, such as the player who swung. mscts compares the entity each server refers to.

## `damage_event.source_direct_id`

**Entity that dealt the damage**

The entity that dealt the damage directly, such as the player's own body for a melee hit, or the arrow for a shot. mscts compares the entity each server refers to.

## `damage_event.source_position`

**Damage source position**

Where the damage came from, when no entity dealt it. The client turns the damage tilt away from it.

## `set_entity_motion.entity_id`

**Entity receiving a velocity**

Which entity the velocity is for. mscts compares the entity each server refers to, rather than its server-assigned number.

## `set_entity_motion.velocity.scale`

**Velocity scale**

How the three velocity values are scaled. The packet holds a velocity as a scaled integer for each axis, so a different scale with the same movement shows here.

## `set_entity_motion.velocity.x`

**Velocity x**

The velocity along x. After a hit it is the knockback: a server with a different knockback strength sends a different number, and the entity is thrown another distance.

## `set_entity_motion.velocity.y`

**Velocity y**

The velocity along y. After a hit it is how high the entity is thrown.

## `set_entity_motion.velocity.z`

**Velocity z**

The velocity along z. After a hit it is the knockback along z: a server that takes the attacker's facing differently sends another number.

## `hurt_animation`

**Hurt animation**

A packet that tells the client to play the hurt animation of an entity. Vanilla sends the damage event instead for a hit, so a server that sends this one plays the animation another way.

## `hurt_animation.entity_id`

**Entity playing the hurt animation**

Which entity plays the animation. mscts compares the entity each server refers to, rather than its server-assigned number.

## `hurt_animation.yaw`

**Hurt animation direction**

The direction the damage came from, in degrees. The client tilts the entity away from it.

## `sound`

**Sound**

A packet that tells the client to play a sound at a position, such as the sound of a hit. A server that sends a sound vanilla does not, or leaves one out, plays another sound or none. The pitch and the seed are left out of the comparison, because vanilla draws them at random.

## `sound.sound.reference`

**Sound to play**

Which sound the client plays. A difference plays another sound.

## `sound.category`

**Sound category**

The volume slider that controls the sound, such as players or hostile creatures.

## `sound.x`

**Sound x**

Where the sound plays along x, in eighths of a block.

## `sound.y`

**Sound y**

Where the sound plays along y, in eighths of a block.

## `sound.z`

**Sound z**

Where the sound plays along z, in eighths of a block.

## `sound.volume`

**Sound volume**

How loud the sound is, and how far it carries.

## `animate`

**Entity animation**

A packet that tells the client to play an animation on an entity, such as the stars of a critical hit. A server that leaves it out, or sends another animation, shows the player no critical hit.

## `animate.entity_id`

**Entity playing an animation**

Which entity plays the animation. mscts compares the entity each server refers to, rather than its server-assigned number.

## `animate.action`

**Animation type**

Which animation the client plays, such as a swing of the arm or a critical hit.

## `level_particles`

**Particles**

A packet that tells the client to show particles at a position, such as the hearts a hit shows. A server that leaves it out shows none.

## `level_particles.particle.type`

**Particle type**

Which particle the client shows.

## `level_particles.x`

**Particles x**

Where the particles appear along x.

## `level_particles.y`

**Particles y**

Where the particles appear along y.

## `level_particles.z`

**Particles z**

Where the particles appear along z.

## `level_particles.count`

**Particle count**

How many particles the client shows.
