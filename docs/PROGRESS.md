# Progress

Handoff between sessions. Update it at least every few commits and always
before stopping (see the `red-green` skill).

## Now

Milestone **M0 (Harness)** is done. **M1 (Talk to vanilla)** has started:
VarInt encode/decode is green. Work now runs under the tech-lead/worker
model (`docs/PROCESS.md`).

Done:
- **A** (sonnet): `codec` wire types and framing.
- **B** (opus): `Target`, `ServerSpec`, `Endpoint`, the adapter base
  types, and a complete `VanillaAdapter` (golden-file `server.properties`,
  offline-UUID `ops.json`, hash-verified provision, reference-tier test).
- **C** (opus): `Codec` (`packets.json` 26.3, name ↔ id, strict schema
  mechanism, handshake/status schemas), plus the lead's `Codec.for_target`.
- **E** (opus): vanilla hardening. The `NO_NETWORK` argv (authlib
  discovery → `127.0.0.1:0`, empty hosts file) is strace-verified; plus an
  absolute, release-file-verified Java 25, workdir refusal, and a shared
  `cache_dir()`.

- **D** (opus): `runner.running`, with an injected readiness probe,
  stdin → SIGTERM → SIGKILL of the process group, cleanup on
  error/cancel, a leak guard, and a reference boot of vanilla (about 10 s
  to ready).

In flight:
- **F** (opus): `Transcript`/`Event`/`Mark`, `Connection` (framing, State,
  recording), `Bot.status`/`ping`, and `status_probe`, all hermetic.
- **G** (sonnet): packets.json regen check, and a host-independent
  vanilla launch (env, TZ, IPv4).
- **H** (opus): `PumpkinAdapter`.

## Next

Take the first item. Split it if it is more than one failing test.

1. Reference tier: `running` + `status_probe` launch vanilla, and
   `Bot.status`/`ping` decode strictly against it (ADR-0003). Replace the
   runner test's inline probe with `status_probe`. Add a session-scoped
   Reference Instance fixture so reference tests share one boot (after
   F).
2. `spec`/`adapter`: a distinct loopback host per Instance
   (`ServerSpec.host` in 127/8), so a probe can never reach another
   worker's server.
3. `scripts/` research harness: launch any Adapter's LaunchPlan
   (optionally under strace) and probe it; `scripts/strays.py`; a
   reference test asserting that the Reference's connects are
   loopback-only. Also tooling: `pythonpath = ["tests"]` +
   `tests/support/` (sonnet).
4. `runner`: a parent-death guard, so a SIGKILLed harness never orphans
   servers.
5. Spawn: vanilla's join position varies on every fresh run even with
   seed 0. Pin it (spawn radius) or Mask `player_position` before M4.
6. Then **M2** in `docs/PLAN.md`.

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
