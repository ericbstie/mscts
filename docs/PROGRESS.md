# Progress

Handoff between sessions. Update it at least every few commits and always
before stopping (see the `red-green` skill).

## Now

**M1** is done in substance: vanilla is provisioned, hardened and launched,
and it answers strict status/ping through our own Codec, Connection and
Bot. The **M2** Comparison engine is built; wiring (Scenario registry,
Run, `selfcheck`) is next. The first Candidate (Pumpkin) has an Adapter,
but it is blocked on user decisions (see below).

Integrated workers: A (wire+framing), B (vanilla adapter), C (Codec),
D (runner), E (vanilla network isolation), F (Transcript, Connection,
Bot), G (regen + host-independent launch), H (Pumpkin adapter), I
(tooling + shared Reference), J (Comparison engine), K (foundation audit,
`docs/audits/2026-09-26-foundation.md`).

Direction set by the user (ADR-0006): the Report is a raw catalogue of
differences grouped by mechanic, with no declared deviations. Random
mechanics are judged statistically in an opt-in tier; redstone and
glitches are tick-exact; Fixtures use commands only for now.

User decisions (2026-09-26):
1. **Decided.** The Pumpkin Adapter writes a flat world save (and the
   difficulty) in Pumpkin's own format, verified by a join.
2. **Open.** The user wants to discuss this further: Pumpkin provision
   fails here because the proxy's CA for GitHub hosts is rejected by
   Python 3.13's strict X.509 check.
3. **Decided (ADR-0007).** Wire-only Divergences are reported in their own
   section and excluded from compliance scores.

## In flight

- **N** (sonnet): `scripts/mutate.py` trustworthy verdicts (MD6),
  baseline check, `.pyc`-safe restore, and a copy-based parallel batch
  mode; S311 ignore in tests.
- **M** (opus): readiness proves socket ownership (H1); `ServerSpec.host`
  in 127/8 per Instance; MD8, R5, R9, R11, L6.
- **P** (opus): the join flow (login → configuration → play → first chunk
  batch) with a background reader, arrival stamping (H2), recorded decode
  failures (H3a), MD1/MD2/MD4/MD5/L1–L5/L8.

## Next

Take the first item. Split it if it is more than one failing test.

1. M2 wiring (opus): the `@scenario` registry (with a Scenario kind per
   ADR-0006), `status/basic` + `status/ping`, a Run over two Instances,
   Candidate-caused failures → `mismatch` (H3b), `mscts selfcheck` →
   `match`, and the first Measurements (after M and P).
2. `scripts/` research harness (sonnet): netns sandbox, strace summary,
   join probe (adopt worker H's scratch tools), and a loopback-only
   reference test.
3. `runner`: a parent-death guard.
4. Tick research (opus, ADR-0006): is `/tick freeze`/`/tick step`
   observable over the protocol (`ticking_state`, `ticking_step`,
   `set_time`)? Design tick-indexed observation anchored on world age.
5. Statistical tier design (opus, ADR-0006): the distribution test,
   confidence, N, and a per-kind Self-check; first Scenario
   `spawn/join-position`.
6. Flake hunt: the unit tier under CPU stress, N times.
7. `adapter/pumpkin` (opus, after M): write a flat world save and the
   difficulty in Pumpkin's own format (level.dat at its DataVersion plus
   flat `world_gen_settings.dat`), lift `LIMITS` for them, and verify with
   a join (spawn y = -60, chunk contents).
8. `compare` (opus, ADR-0007): classify Divergences as observable or
   wire-only; add declared-default canonicalizations, each cited from
   the client decoder.

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
