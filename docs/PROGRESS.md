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

Awaiting user decisions:
1. A Candidate that cannot honour a ServerSpec field (Pumpkin: no flat
   world, difficulty ignored).
2. Pumpkin provision fails here: the proxy's CA for GitHub hosts is
   rejected by Python 3.13 strict X.509.
3. Canonicalize "declared defaults" (missing `players.sample` ≡ `[]`)?

## Next

Take the first item. Split it if it is more than one failing test.

1. Tooling (sonnet): fix `scripts/mutate.py` (MD6 false KILLED, no-op
   sanity run, `PYTHONDONTWRITEBYTECODE=1`, a parallel copy-based batch
   mode); S311 ignore in `tests/**`; then re-verify earlier "bites" claims
   for the critical modules.
2. Audit fix batch (opus), from `docs/audits/2026-09-26-foundation.md`:
   - H1: readiness must prove the Instance owns the socket, plus a
     distinct loopback host per Instance;
   - H2: stamp receive time at arrival (background reader);
   - H3: record undecodable frames and make Candidate-caused failures
     `mismatch`;
   - MD1–MD5 and MD8; delete `FrameDecoder.feed`.
3. M2 wiring (opus): the `@scenario` registry, `status/basic` +
   `status/ping`, a Run over two Instances, `mscts selfcheck` → `match`,
   and the first Measurements.
4. Join brief (opus): compression, login → configuration → play up to the
   first chunk batch, keep-alive/teleport answering.
5. `scripts/` research harness (sonnet): netns sandbox, strace summary,
   join probe (adopt worker H's scratch tools), and a loopback-only
   reference test.
6. `runner`: a parent-death guard.
7. Spawn (ADR-0006): exact Scenarios pin the position with a Fixture
   (`/setworldspawn`, `/tp`); a statistical `spawn/join-position` Scenario
   comes in M6b. Never Mask it.
8. Flake hunt: the unit tier under CPU stress, N times.

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
