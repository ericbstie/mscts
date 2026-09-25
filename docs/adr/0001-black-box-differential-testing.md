# ADR-0001: Black-box differential testing over the wire protocol

Status: accepted (2026-09-25)

## Context

The suite must stay as server-agnostic as possible. Candidates differ in
language, config format, console and admin APIs. The only interface they
all implement is the Java Edition wire protocol at one protocol version.
"Compliance" means behaving like vanilla, so vanilla is the natural oracle.

We also considered server hooks: RCON, stdin console, and vanilla's
JSON-RPC management API. The rule was to adopt them only if they are both
significantly easier and easy to move away from. They are not
significantly easier. Unsigned `chat_command` packets from an operator bot
are no harder to send than RCON frames. Operator status has to be granted
per server either way, and command feedback already arrives as
`system_chat`. The management API is vanilla-only.

## Decision

- mscts observes and drives servers **only as protocol clients** (Bots).
- Compliance is **differential**. The same Scenario runs against the
  Reference and the Candidate, both Transcripts are normalized with Masks,
  and they are diffed into a Verdict. Scenarios do not hard-code expected
  values that vanilla could produce.
- Fixtures are set up through **Control**, which by default is an Operator
  Bot sending vanilla command syntax. Control is an interface, so a
  console or RCON implementation can be added per Adapter later without
  touching Scenarios.
- If a Candidate cannot satisfy a Scenario's prerequisites (such as a
  command it lacks), the Scenario's Verdict is `blocked`, not `mismatch`.
- Timing is measured client-side from Transcript timestamps. Process
  metrics (startup, RSS) come from the generic process runner, not from
  Adapters.

## Consequences

- Adding a Candidate means writing one Adapter. Scenarios never change per
  Candidate.
- Every Scenario must pass the Self-check (Reference vs Reference) before it
  is trusted. This forces all nondeterminism to be declared as Masks.
- Behaviour visible only server-side (such as disk format) is out of
  scope unless it becomes observable over the protocol.
