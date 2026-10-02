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

## `block_entity_data`

**Block entity data**

The data of a block that holds some, such as the text of a sign. A server
that leaves it out, or sends other data, shows a blank sign or different
text. A chest's items are not sent in it; the `blocks` Groups read them
with a command instead, and compare the answer as `system_chat`.

## `block_update`

**Single block change**

One block changing at one position, as `/setblock` does. A server that
sends a change vanilla does not, or leaves one out, shows the player a
different world. Its fields have their own test cases, below.

## `block_update.block_state`

**Single block change state**

The state the block changes to. Each block, with its properties such as
which way a stair faces, has its own number, so a different number shows
a different block or a differently turned one.

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

## `level_event`

**World event**

An effect the client plays at a position, such as the particles and sound
of a block breaking. A server that leaves it out shows no effect.

## `level_event.event_id`

**World event type**

Which effect plays. Vanilla sends 2001, a block breaking, with the state of
the broken block as its data. A different number plays a different effect.

## `section_blocks_update`

**Block changes in a section**

Many blocks changing in one chunk section, a part of a chunk 16 blocks
high, at once, as `/fill` and `/clone` do. It holds the section's position
and a list of changes. Each change has its own test cases, below.

## `section_blocks_update.blocks[]`

**Block change in a section**

One change in the list, or a change only one server sent. mscts compares
the list in the order it is sent, and vanilla sends it in the order of a
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

## `set_entity_data`

**Entity data**

The data of an entity, such as which item a dropped item holds and how many.
A different value shows the player a different item or count.

## `status_response.description`

**Server list description**

The server's description in the multiplayer server list. This test case
compares its original format: vanilla's `"mscts"` and Pumpkin's
`{"text": "mscts"}` display the same text, so that difference is network
traffic only. Differences in the text the client reads are compared below.

## `status_response.description.text`

**Server list description text**

The description text after mscts gives equivalent text components one
form. A different value changes the description a player reads in the
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

## `status_response.version.name`

**Server version name**

The version name the server advertises, such as `26.3`. A different name
changes the version text the client can show for an incompatible server.
It is separate from the protocol number that determines compatibility.

## `status_response.version.protocol`

**Protocol version**

The protocol number the server advertises. A different value can make the
client show the server as incompatible. The Target's protocol number is
777; this comparison checks the advertised value, not every packet layout.

## `status:pong_response.timestamp`

**Server list ping response**

The value returned for a server list ping. The server should echo what
the client sent. A different value breaks that exchange; the time until
the answer arrives is measured separately as `status.rtt`. The `status:`
prefix distinguishes this packet from a pong in another protocol state.

## `system_chat`

**Chat message from the server**

A message the server shows in the chat, such as the answer to a command.
A server that leaves it out, or sends one more, shows the player a message
vanilla does not. mscts keeps the order of the packets in a window, so a
command's answer that comes after the block changes it makes, where
vanilla sends it before them, is reported as left out in one place and
sent in another.

## `system_chat.content`

**Chat message text**

The message's text component. mscts compares its bytes, so the same
message written another way also differs here. The translation key in the
bytes, such as `commands.setblock.success`, says what the message is.
