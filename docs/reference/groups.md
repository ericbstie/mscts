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

`status/with-player` waits 6 seconds after the join before it asks:
vanilla builds its status again every 5 seconds, and the wait is that
interval and one second. A server whose status lasts longer shows no
player, and the Report shows that as a difference.

No status Group has a Mask. Nothing in a status exchange is an identifier
without gameplay meaning, so every difference in it is a Divergence.

## Blocks (`blocks`)

What `/setblock`, `/fill` and `/clone` do to the world. A Bot called `builder`, which is an
operator, runs each command itself, in a window of its own. The Group compares the blocks the
command changes, the data of the block entities, the break particles, the items a block drops,
and the message the server answers the builder with.

The world is frozen and random ticks are off while a Group runs, so nothing changes a block but
the command. Both settings are put back afterwards, and so are the blocks. Every block a Group
changes is in the chunk the builder is sent when it joins, the one that holds x and z from 0 to 15.

Vanilla puts a player who joins at a random place near the world spawn, so the builder could
stand where a command sets a block. It would then crawl and take damage, and the server would
tell it so. To keep that out of the comparison, the builder is moved with `/tp` to x 0.5, y -60,
z 14.5 before the first window, away from every block a Group changes. So the blocks Groups
require `/tp`: on a server without it, all three are `blocked`.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `blocks/setblock` | exact | none | Runs `/setblock` in each mode (`destroy`, `keep`, `replace`, `strict`), on air and on a block. Then it sets a block with states, a sign with text, a chest with an item, and the block that is already there. Last, it reads the chest back with `/data get block`. | none |
| `blocks/fill` | exact | none | Runs `/fill` over a region of 5 by 5 by 5 blocks that crosses a chunk section border, with blocks already in it: with no mode, with each mode (`destroy`, `hollow`, `keep`, `outline`, `replace`, `strict`), and with `replace` and a block to replace. | none |
| `blocks/clone` | exact | none | Runs `/clone` on a box of 3 by 3 by 3 blocks that holds stone, dirt, a sign with text, a stair, a chest with an item and air: with each of `replace`, `masked` and `filtered`, each with `normal`, `force` and `move`. Then it clones the box onto a box that overlaps it, with `normal`, `force` and `move`. Last, it reads the copied chest back with `/data get block`, after a `normal` and a `move` clone. | none |

A block dropped in `destroy` mode starts at a random place and speed. `blocks/setblock` and
`blocks/fill` leave out where the item appears (`x`, `y` and `z` in `add_entity`), its sideways
speed (`velocity.x` and `velocity.z`) and which way it faces (`yaw`). Which item drops, and how
many, is still compared. `/clone` drops nothing, so `blocks/clone` has no such Mask.

The server does not send a chest's items to a player who is only watching it, so a window cannot
see them in the block packets. The builder reads them with `/data get block`, and the message it
gets back is compared.

The `/fill` region holds one block that drops an item. Vanilla sends the items a tick drops in an
order that follows their entity ids, and two servers number their entities differently, so with
several the Reference would not match itself.

## Joining a world (`join`)

What a player receives when it joins, up to the end of the first chunk batch: the login, the configuration (registries, tags and enabled features) and the first play packets (the world, difficulty, abilities, position, inventory, health, experience, recipes, advancements, the world border and the first chunks).

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `join/basic` | exact | none | One player joins alone and receives the first chunk batch. The player spawns exactly at the world spawn (`gamerule respawn_radius 0`), the check that repeats its first position is off (`gamerule player_movement_check false`), and so is natural regeneration (`gamerule natural_health_regeneration false`), which in peaceful raises the player's saturation for as long as it stays online. Once the player has left, the rules are set back to vanilla's defaults, not to the values the server had before. | `join.to_first_chunk` |

The comparison ends when the first chunk batch is complete. Later batches, and the animals that walk into view, depend on timing.

## Planned

| Mechanic | First Group | Needs |
| --- | --- | --- |
| Redstone and glitches | Tick-by-tick observation under `/tick freeze` and `/tick step` | The `tick-exact` kind. |
| Spawning and loot | Distributions over many runs | The `statistical` kind, in its own opt-in tier. |

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
