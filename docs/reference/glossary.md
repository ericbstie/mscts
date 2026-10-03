---
outline: 2
---

# Glossary

These definitions follow [`CONTEXT.md`](https://github.com/ericbstie/mscts/blob/main/CONTEXT.md).

## Servers

### Target

The pinned (Minecraft version, protocol version) pair a Run
speaks, e.g. `26.3 / 777`. Every server in a Run must speak the Target.

### Reference

The vanilla server for the Target. It is the oracle, so
whatever it does is correct by definition.

### Candidate

The custom server implementation being measured
(Pumpkin, Minestom, …).

### Adapter

The only server-specific code. It checks that a binary is
a server it can run and turns a ServerSpec into a LaunchPlan. It never
downloads or installs anything. Reference and every Candidate each have
one.

### ServerSpec

A server-agnostic, declarative description of how a
server must be configured (the host and port of its Endpoint, view
distance, world preset, operators, …). Offline mode, no encryption, no
whitelist, no pause when empty, no telemetry, and no outbound
(non-loopback) network connections are invariants, not options. The host
is always a loopback address (127.0.0.0/8), and each Instance gets one of
its own.

### Installation

The binaries installed for an Adapter and a Target,
cached on disk, with a recorded source (a registry entry or `--from`
file) and sha256. It is created only by `mscts adapter install`, or
after an explicit prompt (ADR-0008).

### Registry

The maintainer-approved list of installable servers, each
pinned by version and checksum. It never trusts a name alone. One
**entry** is (adapter, version label, Target, URL, sha256 and/or the
publisher's hash), named `<adapter> <version>` (`pumpkin
nightly-b8382a8a`). A floating URL such as Pumpkin's nightly is only an
entry for the one build its sha256 pins.

### LaunchPlan

The argv, cwd, env and stop method an Adapter produces.
It contains no process handling.

### Instance

One running server process started from a LaunchPlan and
reachable at an **Endpoint** (host, port). It is **ready** when a status
ping answers with the Target protocol **and** the socket listening at the
Endpoint is provably the Instance's own (**ownership**: held by its process
group, the same socket before and after the ping). An answer from any other
process at the same Endpoint never makes an Instance ready.

## Talking to a server

### Codec

The field types (VarInt, String, NBT, …) and packet schemas for
the Target. Packet IDs come from the vanilla-generated `packets.json`.

### Packet

One decoded frame: state, direction, name
(`minecraft:login`), raw bytes, and fields if a schema exists.

### Bot

One client connection driven by a Group. It answers by itself
what the vanilla client answers by itself (keep-alives, teleports, chunk
batches, the configuration acks), whether or not its Group is reading.

### Join

A Bot's way into the game, offline: handshake, login,
configuration, then play until the server's first chunk batch has
finished.

### Control

The channel used to set up Fixtures. By default it is an
**Operator Bot** that sends vanilla command syntax: a Bot called
`control`, which every Adapter makes an operator. It runs each command,
then a marker command, and returns once the server has answered the
marker and passed the barrier. What it receives is recorded but never
compared, and a Candidate without one of its commands makes the Group
`blocked`. Control can leave (its Bot closes), and its next command
joins a new one.

### Fixture

World or player state established before the observed part
of a Group.

## Testing

### Group

A set of actions played against both servers, named like
`status/basic`. Each Instance it plays against gives one Transcript. It
declares ServerSpec overrides and prerequisites.

### Group kinds

(ADR-0006; `GroupKind` in code, a Group's `kind`,
exact unless it says otherwise):
- **exact**: deterministic, diffed packet by packet;
- **tick-exact**: deterministic mechanics (redstone, glitches) observed
  tick by tick under a frozen and stepped world;
- **statistical**: random mechanics (spawning, loot) run N times per
  server and compared as distributions.

### Transcript

The ordered, timestamped record of every Packet each Bot
sent and every Packet it took from what it received, plus Marks.

### Event

One entry of a Transcript: a Packet one Bot sent or received,
and when: a sent Packet when it was written, a received one when it
arrived (not when the Bot took it).

### Mark

A named timestamp a Group records so a Measurement can be
computed, or an Observation window found.

### Observation window

The part of a Group whose play packets are
compared: what a Bot receives inside `async with context.observe():`,
found by when each packet arrived. It never compares the **heartbeat
packets** (`compare.HEARTBEAT` by name and `compare.HEARTBEAT_PAYLOADS`
by name and first bytes, each with its reason): packets a server sends
on a clock whatever a Group does (keep-alives, the time of day,
vanilla's player latency updates).
A window can be narrowed to named packets. Status, login and
configuration packets are compared whole, and so is every packet of a
Group with no window. When a window closes, each Bot in play first
passes the **barrier** (`Bot.sync`). It asks the server for its
statistics, waits 5 ms after the answer arrives, and asks again. The
second answer comes from a later tick, so by then the server has sent
everything caused by what the Bot sent before. The Bot then takes what
has already arrived (the **drain**). A window can
instead end at a packet's arrival (`until`): no barrier, and it closes
when the first packet of that name arrived at a Bot.

### Mask

A normalization rule that excludes an identifier with no
gameplay meaning (keep-alive ids, teleport ids) from
Comparison. It hides the value only: a field one side lacks, or holds
no value in, is still a Divergence. Anything a player could notice is never masked, even when
it is random; that is judged statistically instead (ADR-0006). Entity
ids need no Mask, and may not have one: every Comparison names each
entity spawned before the window by its type and its position at its
first `add_entity` before the window (a player by its UUID; a masked
axis reads `<masked>`), and numbers each Bot's other entities in the
order it first hears of them (#21, #116). A Mask on a value that holds an entity id hides the id
too, and its reason is the only guard.

### Random field

A field whose value vanilla draws at random, or reads from its clock, on
every run, such as the login's session id, a sound's seed or when an
advancement criterion was obtained (`compare.RANDOM_FIELDS`, each with
its reason).
Every Comparison masks it, whatever the Group, because two vanilla runs
would differ; how it is distributed is a statistical Group's job
(ADR-0011).

### Unordered list

A list vanilla sends in an order that changes from
one boot (or join) to the next while the client keeps its entries in a
map or a set, such as the tag lists (`compare.UNORDERED`). Every
Comparison sorts it by each entry's key in that map or set, before
anything else, so its order is no Divergence at all.

### Canonicalization

Rewrites a value into one canonical form when the
protocol defines two encodings as meaning the same thing to the vanilla
client (a text component `"x"` is `{"text": "x"}`). It is not a Mask: a
Mask declares a value nondeterministic, Canonicalization declares two
values equal. It classifies rather than erases: a difference it makes
equal is still reported, as network traffic (ADR-0007). Its entries form
**the canonical table** (never called a registry).

### Comparison

Normalizes the Reference and Candidate Transcripts of one
Group (Canonicalization, then Masks) and diffs them into a Verdict.

### Divergence

One difference found by a Comparison. It is
**gameplay** (a vanilla client could tell the two values apart, so a
player could notice it) or **network traffic** (the servers send the
same thing in different formats, and a vanilla client ends up with the
same result): its `observability`. Network traffic Divergences are
listed alongside gameplay differences and excluded from compliance scores
(ADR-0007, ADR-0012);
`Verdict.gameplay` is what scores count.

### Test case

One field a Comparison compares, named after its
packet and its path in it (`status_response.players.max`,
`play:keep_alive.id`). The name leaves out list indices and which of
several same-named packets it was, so it is the same in every run.
Every compared field is one, so nobody lists them by hand. A packet
compared as a whole (by payload, missing or unexpected) is the test
case of its packet name. A masked field is a test case only where one
side lacks it, and packets an Observation window leaves out are none. Each test
case in a Verdict is the same, different in gameplay, or different in
network traffic only: gameplay if any of its Divergences is.

### Verdict

`match`, `mismatch` (has Divergences), `blocked` (a
prerequisite Group did not match), or `error` (the harness failed, or
the Reference itself could not run the Group). A failure the
Candidate caused (a frame that does not decode, an answer that breaks
the protocol, no answer in time, a connection closed, reset or refused,
or players still online from the Group before) is a `mismatch`, led by
a `failed` Divergence that says what happened, never an `error`:
compliance scores leave `error` out, so a Candidate must never score
better by failing. The same holds while mscts waits for the players of
the Group before to leave; it then does not play the Group.

### Self-check

A Comparison of Reference against Reference. It must
always be `match`. Anything else is a missing Mask or a flaky Group,
never a Reference bug.

### Measurement

A named value with a unit, derived from a Transcript's
span Marks (`status.rtt`, ms) or from the Run itself
(`instance.startup`, ms: launch to ready).

### Run

A set of Groups executed against the Reference and one
Candidate, repeated N times. It produces a **Report**. Each side of a
Run either launches its own Instances (a Server) or is **Attached**: an
Instance someone else launched and stops, which the Run only plays
against, and only for Groups of the ServerSpec it was launched from.

## Development

### Tier

A class of dev tests, chosen by how much real infrastructure
the tests need:
- `unit`: hermetic. No external network, no Java, no Candidate.
  Localhost sockets and short helper processes are allowed.
- `reference`: needs a live vanilla Instance.
- `selfcheck`: needs two live vanilla Instances. One test per registered
  Group, each a Self-check, parametrised from `GROUPS`.
- `candidate`: needs a live Candidate Instance.
- `statistical`: opt-in, slow. Runs statistical Groups N times;
  never part of `check` or the default Run.
