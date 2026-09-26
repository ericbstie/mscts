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
- **Adapter**: the only server-specific code. It checks that a binary is
  a server it can run and turns a ServerSpec into a LaunchPlan. It never
  downloads or installs anything. Reference and every Candidate each have
  one.
- **ServerSpec**: a server-agnostic, declarative description of how a
  server must be configured (the host and port of its Endpoint, view
  distance, world preset, operators, …). Offline mode, no encryption, no
  whitelist, no pause when empty, no telemetry, and no outbound
  (non-loopback) network connections are invariants, not options. The host
  is always a loopback address (127.0.0.0/8), and each Instance gets one of
  its own.
- **Installation**: the binaries installed for an Adapter and a Target,
  cached on disk, with a recorded source (a registry entry or `--from`
  file) and sha256. It is created only by `mscts adapter install`, or
  after an explicit prompt (ADR-0008).
- **Registry**: the maintainer-approved list of installable servers, each
  pinned by version and checksum. It never trusts a name alone. One
  **entry** is (adapter, version label, Target, URL, sha256 and/or the
  publisher's hash), named `<adapter> <version>` (`pumpkin
  nightly-48cba7ee`). A floating URL such as Pumpkin's nightly is only an
  entry for the one build its sha256 pins.
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
- **Bot**: one client connection driven by a Scenario. It answers by itself
  what the vanilla client answers by itself (keep-alives, teleports, chunk
  batches, the configuration acks), whether or not its Scenario is reading.
- **Join**: a Bot's way into the game, offline: handshake, login,
  configuration, then play until the server's first chunk batch has
  finished.
- **Control**: the channel used to set up Fixtures. By default it is an
  **Operator Bot** that sends vanilla command syntax.
- **Fixture**: world or player state established before the observed part
  of a Scenario.

## Testing

- **Scenario**: a deterministic, named script (`status/basic`) that runs
  against one Instance and produces a Transcript. It declares ServerSpec
  overrides and prerequisites.
- **Scenario kinds** (ADR-0006; `ScenarioKind` in code, a Scenario's `kind`,
  exact unless it says otherwise):
  - **exact**: deterministic, diffed packet by packet;
  - **tick-exact**: deterministic mechanics (redstone, glitches) observed
    tick by tick under a frozen and stepped world;
  - **statistical**: random mechanics (spawning, loot) run N times per
    server and compared as distributions.
- **Transcript**: the ordered, timestamped record of every Packet each Bot
  sent and every Packet it took from what it received, plus Marks.
- **Event**: one entry of a Transcript: a Packet one Bot sent or received,
  and when: a sent Packet when it was written, a received one when it
  arrived (not when the Bot took it).
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
  values equal. It classifies rather than erases: a difference it makes
  equal is still reported, as wire-only (ADR-0007). Its entries form
  **the canonical table** (never called a registry).
- **Comparison**: normalizes the Reference and Candidate Transcripts of one
  Scenario (Canonicalization, then Masks) and diffs them into a Verdict.
- **Divergence**: one difference found by a Comparison. It is
  **observable** (a vanilla client could tell the two values apart) or
  **wire-only** (the bytes differ but they decode identically): its
  `observability`. Wire-only Divergences are reported separately and
  excluded from compliance scores (ADR-0007); `Verdict.observable` is
  what scores count.
- **Verdict**: `match`, `mismatch` (has Divergences), `blocked` (a
  prerequisite Scenario did not match), or `error` (the harness failed, or
  the Reference itself could not run the Scenario). A failure the
  Candidate caused (a frame that does not decode, an answer that breaks
  the protocol, no answer in time, a connection closed, reset or refused)
  is a `mismatch`, led by a `failed` Divergence that says what happened,
  never an `error`: compliance scores leave `error` out, so a Candidate
  must never score better by failing.
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
