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
- **Adapter**: the only server-specific code. It says where to download its
  server's latest build for the Target, reads which build a binary is and
  checks that it can run it, and turns a ServerSpec into a LaunchPlan.
  It never installs anything. The Reference and every Candidate each have one.
- **ServerSpec**: a server-agnostic, declarative description of how a
  server must be configured (the host and port of its Endpoint, view
  distance, world preset, operators, …). Offline mode, no encryption, no
  whitelist, no pause when empty, no telemetry, and no outbound
  (non-loopback) network connections are invariants, not options. The host
  is always a loopback address (127.0.0.0/8), and each Instance gets one of
  its own.
- **Installation**: the binaries installed for an Adapter and a Target,
  cached on disk with their build (its version, and its commit where
  the publisher names one), their sha256 and their source (the URL the
  Adapter gave, or a `--from` file). It is created only by
  `mscts adapter install`, or after an explicit prompt (ADR-0008).
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
- **Bot**: one client connection driven by a Group. It answers by itself
  what the vanilla client answers by itself (keep-alives, teleports, chunk
  batches, the configuration acks), whether or not its Group is reading.
- **Join**: a Bot's way into the game, offline: handshake, login,
  configuration, then play until the server's first chunk batch has
  finished.
- **Control**: the channel used to set up Fixtures. By default it is an
  **Operator Bot** that sends vanilla command syntax: a Bot called
  `control`, which every Adapter makes an operator. It runs each command,
  then a marker command, and returns once the server has answered the
  marker and the Bot has passed the barrier. What it receives is recorded but never
  compared, and a Candidate without one of its commands fails the Group
  (`missing /tick`). Control can leave (its Bot closes), and its next command
  joins a new one.
- **Fixture**: world or player state established before the observed part
  of a Group.

## Testing

- **Group**: a set of actions played against both servers, named like
  `status/basic`. Each Instance it plays against gives one Transcript. It
  declares ServerSpec overrides and prerequisites.
- **Group kinds** (ADR-0006; `GroupKind` in code, a Group's `kind`,
  exact unless it says otherwise):
  - **exact**: deterministic, diffed packet by packet;
  - **tick-exact**: deterministic mechanics (redstone, glitches) observed
    tick by tick under a frozen and stepped world;
  - **statistical**: random mechanics (spawning, loot) run N times per
    server and compared as distributions.
- **Transcript**: the ordered, timestamped record of every Packet each Bot
  sent and every Packet it took from what it received, plus Marks.
- **Event**: one entry of a Transcript: a Packet one Bot sent or received,
  and its time. A sent Packet is timed when it was written, a received one
  when it arrived (not when the Bot took it).
- **Mark**: a named timestamp a Group records so a Measurement can be
  computed, or an Observation window found.
- **Observation window**: the part of a Group whose play packets are
  compared: what a Bot receives inside `async with context.observe():`,
  found by when each packet arrived. It never compares the **heartbeat
  packets** (`compare.HEARTBEAT` by name and `compare.HEARTBEAT_PAYLOADS`
  by name and first bytes, each with its reason): packets a server sends
  on a clock, regardless of what a Group does (keep-alives, the time of day,
  vanilla's player latency updates).
  A window can be narrowed to named packets. Status, login and
  configuration packets are compared whole, and so is every packet of a
  Group with no window. Before a window opens, and when it closes, each
  Bot in play first passes the **barrier** (`Bot.sync`). It asks the server for its
  statistics three times, each 5 ms after the previous answer arrived. The
  last answer comes from a later tick than the first, so by then the
  server has sent everything caused by what the Bot sent before. Two
  `award_stats` the server sends unasked during one barrier can still
  end it early (ADR-0010). Each Bot's window ends
  at its own barrier's last answer, regardless of what the other Bots are
  still waiting for. A Bot created after the window ends is outside it. A
  barrier covers what its own Bot sent, so a window that must hold
  what another Bot's action causes waits for that action's feedback
  before it ends. The Bot then takes what has already arrived (the
  **drain**), outside its window. A window can
  instead end when a packet arrives (`until`): there is no barrier, and it
  closes when the first packet of that name arrives at any Bot, or at the
  Bot named with `bot=`. _Avoid_: phase,
  section.
- **Mask**: a normalization rule that excludes an identifier with no
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
- **Random field**: a field whose value vanilla draws at random, or reads from its clock, on
  every run, such as the login's session id, a sound's seed or when an
  advancement criterion was obtained (`compare.RANDOM_FIELDS`, each with
  its reason).
  Every Comparison masks it, whatever the Group, because two vanilla runs
  would differ; how it is distributed is a statistical Group's job
  (ADR-0011).
- **Unordered list**: a list vanilla sends in an order that changes from
  one boot (or join) to the next while the client keeps its entries in a
  map or a set, such as the tag lists (`compare.UNORDERED`). Every
  Comparison sorts it by each entry's key in that map or set, before
  anything else, so its order is never a Divergence.
- **Canonicalization**: rewrites a value into one canonical form when the
  protocol defines two encodings as meaning the same thing to the vanilla
  client (a text component `"x"` is `{"text": "x"}`). It is not a Mask: a
  Mask declares a value nondeterministic, Canonicalization declares two
  values equal. It classifies rather than erases: a difference it makes
  equal is still reported, as network traffic (ADR-0007). Its entries form
  **the canonical table** (never called a registry).
- **Comparison**: normalizes the Reference and Candidate Transcripts of one
  Group (Canonicalization, then Masks) and diffs them into a Verdict.
- **Divergence**: one difference found by a Comparison. It is
  **gameplay** (a vanilla client could tell the two values apart, so a
  player could notice it) or **network traffic** (the servers send the
  same thing in different formats, and a vanilla client ends up with the
  same result): its `observability`. Network traffic Divergences are
  listed alongside gameplay differences, and a test case that differs
  only in network traffic passes (ADR-0007, ADR-0012).
- **Test case**: one field a Comparison compares, named after its
  packet and its path in it (`status_response.players.max`,
  `play:keep_alive.id`). The name leaves out list indices and which of
  several same-named packets it was, so it is the same in every run.
  Every compared field is one, so nobody lists them by hand. A packet
  compared as a whole (by payload, missing or unexpected) is the test
  case of its packet name. A masked field is a test case only where one
  side lacks it, and packets an Observation window leaves out are not test cases. Each test
  case in a Verdict is the same, different in gameplay, or different in
  network traffic only: gameplay if any of its Divergences is. A name
  that only network traffic Divergences give, where no compared field
  has it, is not in the Verdict's test cases. The Report lists it but
  does not score it (#330). _Avoid_:
  check, test (for one compared field).
- **Verdict**: `match`, `mismatch` (has Divergences), `blocked` (a
  prerequisite Group was not run, so the Group was played on neither
  server; a Run refuses that now, so only an older report.json has it),
  or `error` (the harness failed, the Reference itself could not run the
  Group, or a prerequisite is an `error`). A prerequisite passes if it
  is a `match`, or a `mismatch` only in network traffic. A Group that
  fails on
  the Candidate and not on the Reference is a `mismatch`, led by a
  `failed` Divergence that says what happened, never an `error`. That
  holds whatever the failure: a frame that does not decode, an answer
  that breaks the protocol, no answer in time, a connection closed, reset
  or refused, a missing command that Control sends, players still online
  from the previous Group, or a value the Group does not expect. The Score
  leaves `error` out, so a Candidate must never score better by failing.
  The same holds while mscts waits for the previous Group's players to
  leave, after a Group left the Candidate's world frozen (#266), and when
  the Candidate failed a prerequisite (#285). mscts then plays the Group
  on the Reference alone, and the Candidate fails each test case of that
  play.
- **Self-check**: a Comparison of Reference against Reference. It must
  always be `match`. Anything else is a missing Mask or a flaky Group,
  never a Reference bug.
- **Measurement**: a named value with a unit, derived from a Transcript's
  span Marks (`status.rtt`, ms) or from the Run itself
  (`instance.startup`, ms: launch to ready).
- **Run**: a set of Groups executed against the Reference and one
  Candidate, repeated N times. It produces a **Report**. Each side of a
  Run either launches its own Instances (a Server) or is **Attached**: an
  Instance someone else launched and stops, which the Run only plays
  against, and only for Groups that use the ServerSpec it was launched from.
- **Score**: the share of a Report's scored lines that passed, as in
  `35 passed, 5 failed. (87.5%)` (#101). Each line is one test
  case of one Group, or the Group's own line. A test case fails if it
  differs in gameplay in any repetition, or if the Candidate failed its
  whole Group, or a prerequisite of it, in any repetition (#262, #285).
  A Group whose prerequisite the Candidate failed is still played on the
  Reference, so its test cases are that play's. A blocked Group is played
  on neither server, and fails no test case. One whose prerequisite is
  an `error` is an `error` too, so vanilla failing a prerequisite costs
  the Candidate nothing. A Group's own line fails for a blocked Group or
  a Candidate failure; an `error` is not scored. Nor is a test case
  that no compared value names, such as a key the vanilla client
  never reads, which is listed only where the two servers send a
  value in different forms (#330). The score is rounded down, so only
  a Run where every scored line passes scores 100%.

## Development

- **Tier**: a class of dev tests, chosen by how much real infrastructure
  the tests need:
  - `unit`: hermetic. No external network, no Java, no Candidate.
    Localhost sockets and short helper processes are allowed.
  - `reference`: needs a live vanilla Instance.
  - `selfcheck`: needs two live vanilla Instances. One test per registered
    Group, each a Self-check, parametrised from `GROUPS`.
  - `candidate`: needs a live Candidate Instance.
  - `statistical`: opt-in, slow. Runs statistical Groups N times;
    never part of `check` or the default Run.
