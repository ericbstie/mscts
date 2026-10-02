# Test case reference

Search the name from a Report to find what mscts compared and what a
difference means. A test case without an entry is still reported by name.
See [Reading a Report](/guide/reading-a-report#test-cases) for how names
describe packet fields and list elements.

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
