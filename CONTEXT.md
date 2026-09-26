# mscts — domain context

mscts runs the same scripted client behaviour against a vanilla Minecraft
server and against a custom server. It diffs what each server sends back
and times how long each takes. Its output is an objective parity score and
a set of performance numbers for the custom server.

Use these terms exactly, in code, tests, commits and docs. If a concept you
need is missing, add it here in the same commit that introduces it.

## Servers

- **Target**: the pinned (Minecraft version, protocol version) pair a Run
  speaks, e.g. `26.3 / 777`. Every server in a Run must speak the Target.
- **Reference**: the vanilla server for the Target. It is the oracle, so
  whatever it does is correct by definition.
- **Candidate**: the custom server implementation being measured
  (Pumpkin, Minestom, …). _Avoid_: SUT, implementation, custom server (in
  code).
- **Adapter**: the only server-specific code. It provisions an
  Installation and turns a ServerSpec into a LaunchPlan. Reference and
  every Candidate each have one.
- **ServerSpec**: a server-agnostic, declarative description of how a
  server must be configured (port, view distance, world preset,
  operators, …). Offline mode, no encryption, no whitelist, no pause when
  empty, no telemetry, and no outbound (non-loopback) network connections
  are invariants, not options.
- **Installation**: the binaries an Adapter has provisioned for a Target,
  cached on disk, with a recorded source (a registry entry or `--from`
  file) and sha256. It is created only by `mscts adapter install`, or
  after an explicit prompt (ADR-0008).
- **Registry**: the maintainer-approved list of installable servers, each
  pinned by version and checksum. It never trusts a name alone.
- **LaunchPlan**: the argv, cwd, env and stop method an Adapter produces.
  It contains no process handling.
- **Instance**: one running server process started from a LaunchPlan and
  reachable at an **Endpoint** (host, port). It is **ready** when a status
  ping answers with the Target protocol **and** the socket listening at the
  Endpoint is provably the Instance's own (**ownership**: held by its process
  group, the same socket before and after the ping). An answer from any other
  process at the same Endpoint never makes an Instance ready.

## Talking to a server

- **Codec**: the wire types (VarInt, String, NBT, …) and packet schemas for
  the Target. Packet IDs come from the vanilla-generated `packets.json`.
- **Packet**: one decoded frame: state, direction, name
  (`minecraft:login`), raw bytes, and fields if a schema exists.
- **Bot**: one client connection driven by a Scenario.
- **Control**: the channel used to set up Fixtures. By default it is an
  **Operator Bot** that sends vanilla command syntax.
- **Fixture**: world or player state established before the observed part
  of a Scenario.

## Testing

- **Scenario**: a deterministic, named script (`status/basic`) that runs
  against one Instance and produces a Transcript. It declares ServerSpec
  overrides and prerequisites.
- **Scenario kinds** (ADR-0006):
  - **exact**: deterministic, diffed packet by packet;
  - **tick-exact**: deterministic mechanics (redstone, glitches) observed
    tick by tick under a frozen and stepped world;
  - **statistical**: random mechanics (spawning, loot) run N times per
    server and compared as distributions.
- **Transcript**: the ordered, timestamped record of every Packet each Bot
  sent and received, plus Marks.
- **Event**: one entry of a Transcript: a Packet one Bot sent or received,
  and when.
- **Mark**: a named timestamp a Scenario records so a Measurement can be
  computed.
- **Mask**: a normalization rule that excludes an identifier with no
  gameplay meaning (entity ids, keep-alive ids, teleport ids) from
  Comparison. Player-observable behaviour is never masked, even when it is
  random; that is judged statistically instead (ADR-0006).
- **Canonicalization**: rewrites a value into one canonical form when the
  protocol defines two encodings as meaning the same thing to the vanilla
  client (a text component `"x"` is `{"text": "x"}`). It is not a Mask: a
  Mask declares a value nondeterministic, Canonicalization declares two
  values equal.
- **Comparison**: normalizes the Reference and Candidate Transcripts of one
  Scenario (Canonicalization, then Masks) and diffs them into a Verdict.
- **Divergence**: one difference found by a Comparison. It is
  **observable** (a vanilla client could tell the two values apart) or
  **wire-only** (the bytes differ but they decode identically). Wire-only
  Divergences are reported separately and excluded from compliance scores
  (ADR-0007).
- **Verdict**: `match`, `mismatch` (has Divergences), `blocked` (a
  prerequisite Scenario did not match), or `error` (the harness failed, or
  the Reference itself could not run the Scenario).
- **Self-check**: a Comparison of Reference against Reference. It must
  always be `match`. Anything else is a missing Mask or a flaky Scenario,
  never a Reference bug.
- **Measurement**: a named timing value derived from a Transcript, e.g.
  `status.rtt_ms`.
- **Run**: a set of Scenarios executed against the Reference and one
  Candidate, repeated N times. It produces a **Report**.

## Development

- **Tier**: a class of dev tests, chosen by how much real infrastructure
  the tests need:
  - `unit`: hermetic. No external network, no Java, no Candidate.
    Localhost sockets and short helper processes are allowed.
  - `reference`: needs a live vanilla Instance.
  - `candidate`: needs a live Candidate Instance.
  - `statistical`: opt-in, slow. Runs statistical Scenarios N times;
    never part of `check` or the default Run.
