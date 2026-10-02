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

`status/ping` sends the fixed Long `20260926` as its ping payload. The
vanilla client sends its clock, but a Group must send the same bytes
every run.

Neither Group has a Mask. Nothing in a status exchange is an identifier
without gameplay meaning, so every difference in it is a Divergence.

## Blocks (`blocks`)

What `/setblock`, `/fill` and `/clone` do to the world. A Bot called `builder`, which is an
operator, runs each command itself, in a window of its own. The Group compares the blocks the
command changes, the data of the block entities, the break particles, the items a block drops,
and the message the server answers the builder with.

The world is frozen and random ticks are off while a Group runs, so nothing changes a block but
the command. Both settings are put back afterwards, and so are the blocks. Every block a Group
changes is in the chunk the builder is sent when it joins, the one that holds x and z from 0 to 15.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `blocks/setblock` | exact | none | Runs `/setblock` in each mode (`destroy`, `keep`, `replace`, `strict`), on air and on a block. Then it sets a block with states, a sign with text, a chest with an item, and the block that is already there. | none |

A block dropped in `destroy` mode starts at a random place and speed. These Groups leave out where
the item appears (`x`, `y` and `z` in `add_entity`), its sideways speed (`velocity.x` and
`velocity.z`) and which way it faces (`yaw`). Which item drops, and how many, is still compared.

## Planned

| Mechanic | First Group | Needs |
| --- | --- | --- |
| Joining a world (`join`) | `join/basic`: log in offline and receive the first chunk batch | Bots can already join; the Group is next. |
| Redstone and glitches | Tick-by-tick observation under `/tick freeze` and `/tick step` | The `tick-exact` kind. |
| Spawning and loot | Distributions over many runs | The `statistical` kind, in its own opt-in tier. |

See [Project status](/status) for the order.

## Built-in Measurements

| Name | Unit | Source |
| --- | --- | --- |
| `status.rtt` | ms | The `status.rtt` span in `status/ping`: from sending the ping to receiving the pong. |
| `instance.startup` | ms | Every Run: from launching a server until it is ready. |
