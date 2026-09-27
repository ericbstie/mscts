---
outline: 2
---

# Glossary

mscts uses these terms with one meaning each, in code, tests and docs. The
full definitions are in
[`CONTEXT.md`](https://github.com/ericbstie/mscts/blob/main/CONTEXT.md).

## Servers

### Target

The Minecraft version and protocol version a Run speaks. Today that is
26.3 and protocol 777.

### Reference

The vanilla server for the Target. Whatever it does is correct by
definition.

### Candidate

The server being measured, such as Pumpkin.

### Adapter

The only server-specific code. It checks that a binary is a server it can
run, and turns a ServerSpec into a LaunchPlan. It never downloads
anything.

### ServerSpec

A server-agnostic description of how a server must be configured. See
[ServerSpec](/reference/server-spec).

### Installation

A server binary in the cache, with a record of its sha256 and where it
came from.

### Registry

The maintainer-approved list of installable server builds, each pinned by
checksum. One entry is named `<adapter> <version>`, such as
`pumpkin nightly-48cba7ee`.

### LaunchPlan

The command line, working directory, environment and stop method an
Adapter returns.

### Instance

One running server process, reachable at an **Endpoint** (host and port).
It is ready once a status ping answers with the Target protocol from a
socket the process itself holds.

## Talking to a server

### Codec

The wire types and packet schemas for the Target. Packet ids come from
vanilla's generated `packets.json`.

### Packet

One decoded frame, with its state, direction, name, raw bytes, and fields
if a schema exists.

### Bot

One client connection driven by a Scenario. It answers what the vanilla
client answers without the player, such as keep-alives.

### Join

A Bot's offline login, through configuration, until the first chunk batch
in play has finished.

### Control

How a Scenario sets up Fixtures. By default, an operator Bot that sends
vanilla commands. Not built yet.

### Fixture

World or player state set up before the observed part of a Scenario.

## Testing

### Scenario

A deterministic, named script, such as `status/basic`, that runs against
one Instance and produces a Transcript.

### Scenario kind

How a Scenario is judged: `exact` (packet by packet), `tick-exact` (tick
by tick in a frozen world) or `statistical` (as distributions over many
runs).

### Transcript

The ordered, timestamped record of every packet each Bot sent and
received, plus Marks.

### Event

One entry of a Transcript. A sent packet is stamped when it was written, a
received one when it arrived.

### Mark

A named timestamp a Scenario records, used to compute Measurements.

### Mask

A rule that excludes an identifier with no gameplay meaning, such as an
entity id, from Comparison.

### Canonicalization

A rule that rewrites a value into one form when the vanilla client reads
two encodings as the same thing. Its rules form the canonical table.

### Comparison

Canonicalizes and masks two Transcripts of one Scenario, then diffs them
into a Verdict.

### Divergence

One difference a Comparison found. It is **observable** if a vanilla
client could tell the two values apart, and **wire-only** if it could not.

### Verdict

`match`, `mismatch`, `blocked` or `error`. See
[How mscts works](/guide/how-it-works#verdicts).

### Self-check

A Comparison of vanilla against vanilla. It must always be `match`.

### Measurement

A named value with a unit, such as `status.rtt` in milliseconds.

### Run

A set of Scenarios played against the Reference and one Candidate, N
times. It produces a **Report**.

### Tier

A class of development tests by the infrastructure they need: `unit`,
`reference`, `candidate` and `statistical`.
