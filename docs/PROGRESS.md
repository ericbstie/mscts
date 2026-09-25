# Progress

Handoff between sessions. Update it at least every few commits and always
before stopping (see the `red-green` skill).

## Now

Milestone **M0 (Harness)** is done. **M1 (Talk to vanilla)** has started:
VarInt encode/decode is green. Work now runs under the tech-lead/worker
model (`docs/PROCESS.md`).

Done: worker **A** (sonnet) finished the `codec` wire types (VarInt,
VarLong, String, UShort, Long, Bool, UUID, strict end) and framing
(`encode_frame`, `FrameDecoder`).

In flight:
- **B** (opus): `Target`, `ServerSpec` and `VanillaAdapter` (`prepare` +
  `provision`).
- **C** (opus): `Codec`, with `packets.json` 26.3, name ↔ id, the schema
  mechanism, and the handshake/status schemas.

## Next

Take the first item. Split it if it is more than one failing test.

1. `codec`: packets.json regen script built on `VanillaAdapter.provision`,
   plus `Codec.for_target(TARGET)` (after B and C land).
2. `runner`: `running(plan, target)` launches, reaches status-ping
   readiness, and stops gracefully (stdin → SIGTERM → SIGKILL); reference
   tier.
3. `net` + `bot`: `Connection` (framing, compression switch, State
   transitions, Transcript hook) and `Bot.status` against the live
   Reference returning protocol 777.
4. `adapter/pumpkin`: provision nightly (record sha256 + version), and a
   complete `pumpkin.toml` enforcing the invariants (offline,
   `encryption = false`, Bedrock off, telemetry off, no favicon, flat
   world if supported).
5. Then **M2** in `docs/PLAN.md`.

## Log

### 2026-09-25 — session 1: research and harness

- Researched the domain against live servers in the container. Findings
  are in `docs/research/2026-09-25-domain.md`: the vanilla 26.3 join
  sequence was verified up to chunk batches, along with default-config
  traps, the 26.3 `accept_teleportation` change, and Pumpkin nightly's
  config and divergences.
- Decisions: ADR-0001…0005 (black-box differential testing, Astral + mise
  toolchain, single Target 26.3/777, translator-only Adapters with
  status-ping readiness, in-repo plan with always-green commits on `main`).
- Removed the inherited generic skills. Added the `red-green` and
  `protocol-research` skills, plus a SessionStart hook that provisions
  mise tools and deps.
- Toolchain: `mise run check` = ruff (ALL) + format check + ty (all rules
  error) + bandit + unit tier. It runs in about 1 s.
- Environment notes: `java` on the default PATH is 21. Java 25 comes from
  mise, so run anything that needs it through `mise run …` or with the
  mise shims on PATH (the hook exports them). The `UV_NATIVE_TLS`
  deprecation warning comes from the container env and is harmless.
