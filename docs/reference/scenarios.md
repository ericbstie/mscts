# Scenarios

These are the Scenarios mscts ships. Each id's first segment is its
mechanic, which the Report uses as a group heading. Pass ids or globs to
`mscts run --scenario`.

## Server list ping (`status`)

What the vanilla client does to fill in a server list entry: a status
handshake, a `status_request`, and then a `ping_request` whose
`pong_response` gives the latency it shows.

| Id | Kind | Requires | What it does | Measurements |
| --- | --- | --- | --- | --- |
| `status/basic` | exact | none | Asks for the status once. | none |
| `status/ping` | exact | none | Asks for the status, then pings with a fixed payload. | `status.rtt` |

`status/ping` sends the fixed Long `20260926` as its ping payload. The
vanilla client sends its clock, but a Scenario must send the same bytes
every run.

Neither Scenario has a Mask. Nothing in a status exchange is an identifier
without gameplay meaning, so every difference in it is a Divergence.

## Planned

| Mechanic | First Scenario | Needs |
| --- | --- | --- |
| Joining a world (`join`) | `join/basic`: log in offline and receive the first chunk batch | Bots can already join; the Scenario is next. |
| World and blocks | Block updates set up with `/setblock` and `/fill` | An operator Bot that sends commands. |
| Redstone and glitches | Tick-by-tick observation under `/tick freeze` and `/tick step` | The `tick-exact` kind. |
| Spawning and loot | Distributions over many runs | The `statistical` kind, in its own opt-in tier. |

See [Project status](/status) for the order.

## Built-in Measurements

| Name | Unit | Source |
| --- | --- | --- |
| `status.rtt` | ms | The `status.rtt` span in `status/ping`: from sending the ping to receiving the pong. |
| `instance.startup` | ms | Every Run: from launching a server until it is ready. |
