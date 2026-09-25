# ADR-0004: Adapters only translate; readiness is a status ping

Status: accepted (2026-09-25)

## Context

Server defaults drift. Vanilla 26.3 turned the whitelist on by default and
pauses ticking when empty. Pumpkin defaults to encryption, telemetry and a
Bedrock listener. Log formats differ per server, so log-based readiness
would need custom code for every server.

## Decision

- An Adapter does two things: `provision` (obtain binaries into a cache,
  verifying hashes where the source publishes them) and `prepare` (write
  the **complete** native config for a ServerSpec and return a
  LaunchPlan). It never starts or stops a process.
- One generic runner launches every LaunchPlan, captures stdout and
  stderr to files, and stops the server (graceful stop command, then
  SIGTERM, then SIGKILL).
- An Instance counts as ready when a status ping returns the Target's
  protocol version. Logs are never parsed.

## Consequences

- `prepare` is pure enough to unit-test: given a ServerSpec, the test
  asserts on the files written.
- Invariants such as offline mode and no whitelist are tested once per
  Adapter in the `unit` tier.
