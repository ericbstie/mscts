# Progress

Handoff between sessions. Update it at least every few commits and always
before stopping (see the `red-green` skill).

## Now

main: `mise run check` passes (1200 unit tests under
pytest-xdist, about 5 s) and `mise run test:reference` passes (11 tests, about
75 s).

- **M1 (talk to vanilla): done.** Provision, hardening (no outbound
  network, fixed env), and a runner with readiness by socket ownership
  and a loopback host per Instance. Status and ping decode strictly.
- **Join (the protocol half of M4): done.** `Bot.join()` reaches play and
  the first chunk batch against vanilla, with a background reader,
  arrival stamps, recorded undecodable frames, and automatic
  keep-alive/teleport/chunk-batch answers. It joins in about 1.25 s.
- **M2 (first Comparison and Self-check): mostly done.** `scenario.py`
  (`SCENARIOS`, `ScenarioKind`), `status/basic` + `status/ping`, `run.py`
  (a Run over two Instances, `selfcheck`), and the H3b rule (a Candidate
  failure is `mismatch` with a `failed` Divergence). The status Self-check
  is `match` 20/20 on the live Reference, with no Mask. Left: the
  `mscts selfcheck` command and Measurements (3a).
- **G5 is red for the reference tier** (about 91 s against 90 s): 2a.
- **M3a (installs): mostly done.** A Registry pinned by checksum
  (`src/mscts/data/registry.toml`), `mscts adapter install/list/status`
  with `--from`, sources recorded in SOURCE.json. Pumpkin nightly-48cba7ee
  is installed in this container's shared cache via `--from`, and
  `mise run test:candidate` passes. `install.require` asks on a TTY and otherwise fails naming the
  command; nothing installs inside a Run or test. `provision` is gone from
  the Adapter contract. The SessionStart hook runs `mise run
  install:reference` (explicit, loud). **M3a done** except the registry
  review flow and M9's `adapter check`.
- **M3 (first Candidate):** needs the Pumpkin world-save work (Next 4).
- Audit K's high findings H1, H2 and H3 are all fixed.

Product direction (maintainer, 2026-09-26):
- **ADR-0006:** a catalogue of differences grouped by mechanic, with no
  declared deviations. Exact, tick-exact (redstone, glitches) and
  statistical (spawning, loot; an opt-in tier) Scenarios. Masks only for
  non-gameplay ids. Commands-only Fixtures, with a Bot fallback if
  blocks become common.
- **ADR-0007:** wire-only Divergences get their own section and are
  excluded from scores.
- **ADR-0008:** explicit idempotent installs (`mscts adapter install`,
  `--from`), an honest TTY prompt, a checksum-pinned maintainer-approved
  registry, and an Adapter authoring guide plus `mscts adapter check`.
  DX is goal G6.
- The Pumpkin Adapter writes a flat world save and the difficulty in
  Pumpkin's own format.

Environment notes:
- In this container, Python 3.13 cannot download from GitHub (the
  proxy's CA fails strict X.509). Pumpkin is provisioned by hand: `curl
  -sSfL -o pumpkin-X64-Linux
  https://github.com/Pumpkin-MC/Pumpkin/releases/download/nightly/pumpkin-X64-Linux`,
  pinned 2026-09-26 at sha256
  `48cba7ee6e255f7d2150435f58228f1ec9cab477f1dee259f47cd24b8f304b0b`.
  The nightly moves, so if a re-fetch hashes differently, record the new
  pin. Install it with `uv run mscts adapter install pumpkin --from
  <file>` (idempotent; `mscts adapter status pumpkin` shows the source).
- The SessionStart hook exports `MSCTS_JAVA` (the real Java 25). Run
  tiers through `mise run`.

## In flight

Batch 2, briefed against `a64a2b5`:
- **U** (opus, `adapter/pumpkin`): a flat world save + difficulty in
  Pumpkin's own format, with a strict minimal NBT writer (Next 4).
- **V** (opus, `compare`, relaunched against `1822a5f` after a rate-limit
  kill): observable vs wire-only
  Divergences, declared defaults from the client decoder, `update_tags`
  order (Next 5).

After batch 2: the opus audit (Next 12).

## Delegated to the helper agent

The maintainer's second agent (Astra) takes GitHub issues labelled
`helper-ready`. Claude stays the primary worker; do not brief a Claude
worker on a delegated item. Open: #2 javap tool, #3 runner parent-death
guard, #4 PLAN public-name check. Their PRs are reviewed and integrated
like a worker branch.

## Next

Take the first item. Split it if it is more than one failing test. Keep
briefs at 3–6 increments and about 1500 lines at most.

2a. `run` (opus): a Run over existing Endpoints, so `selfcheck` uses the
    session-scoped Reference as one side and boots one Instance, not two
    (G5: reference tier ≤ 90 s). Then Bot errors carry the Bot name, so a
    `failed` Divergence names its Bot (G3).
3a. `cli` (sonnet): `mscts selfcheck` over R's library `selfcheck`
    (Installations via `install.require` with the process's Terminal), and the first Measurements (`measure.py`: `status.rtt`,
    `instance.startup`). Split out of item 2 to keep R under 1500 lines
    and off S's `cli.py`.
4. `adapter/pumpkin` (opus, after 3): write a flat world save and the
   difficulty in Pumpkin's own format (level.dat at its DataVersion plus a
   flat `world_gen_settings.dat`), lift `LIMITS` for them, and verify with
   a join (spawn y = -60, chunk contents). Then M3's first Report.
5. `compare` (opus, ADR-0007): classify Divergences as observable or
   wire-only; add declared-default canonicalizations (cited from the
   client decoder); canonicalize the `update_tags` order (a server
   HashMap) before the join Scenario's Self-check.
6. Research tooling (sonnet): ~~`scripts/research/javap.py`~~
   (delegated: issue #2), then the
   `scripts/` research harness: netns sandbox, strace summary, live
   launch/probe, a loopback-only reference test (adopt workers H, L and P
   scratch tools).
7. `join/basic` Scenario + Self-check 20/20 (after 2 and 5), with a spawn
   Fixture (`/setworldspawn`) per ADR-0006. The statistical
   `spawn/join-position` comes later (M6b).
8. Bot fidelity: send brand `custom_payload`, `client_information` and
   `player_loaded` as the vanilla client does; unique Bot names per
   Transcript (L11); dedupe the runner test helpers (L10).
9. ~~`runner`: a parent-death guard~~ (delegated: issue #3).
10. Tick research (opus, M6a) and statistical tier design (opus, M6b),
    per ADR-0006.
11. Tooling: `mutate.py --batch` includes untracked non-ignored files
    (reported twice); ~~a check that every public name in `src/` appears in
    PLAN.md~~ (delegated: issue #4); a `scripts/` save/restore helper (no
    stash).
12. Next audit (opus): due after the next 2–3 batches. Focus on
    `compare.py`, the new net/bot join code and the runner ownership
    logic.

## Log

### 2026-09-26 — session 2: new tech lead

- Local `main` held a stale pre-rewrite history; saved as the local
  branch `backup/stale-local-main` and reset to `origin/main`.
- Worker Q: the unit tier runs under pytest-xdist (`-n auto`), 11.5 s →
  about 5 s, so G5 holds again. `scripts/repeat.py` flake-hunts under CPU
  stress; 25 stressed runs found no flakes, so the integration retry is
  gone.
- Worker T: `install.require` and the honest prompt; `provision` left
  the Adapter contract; live tiers fail fast naming the install command.
- Worker R (M2 wiring): Scenarios, a Run, H3b, `selfcheck`; status
  Self-check 20/20. The lead fixed two integration reds: nondeterministic
  xdist ids from S's fake jars (bd6d44f), and R's Adapter fakes missing
  S's new Protocol members.
- Worker S (M3a): the Registry, `install.py`, `mscts adapter
  install/list/status`, both Adapters on one provision path; Pumpkin
  installed here with `--from`. Stopped before the prompt at the line
  budget (now Next 3b).

### 2026-09-26 — session 1, continued: tech-lead operation

- The main session became tech lead (`docs/PROCESS.md`). 16 worker
  briefs (A–P) ran, 11 of them opus, all ending in retrospectives. More
  than 100 retrospective items are logged with decisions.
- Built: codec, vanilla and Pumpkin Adapters, runner, Connection/Bot,
  Transcript, the Comparison engine, tooling (`mutate.py`, `strays.py`,
  `regen:packets`), and the foundation audit K
  (`docs/audits/2026-09-26-foundation.md`).
- The maintainer set the product direction in ADR-0006 (a catalogue of
  differences, statistical and tick-exact Scenarios, commands-only
  Fixtures, no declared deviations), ADR-0007 (wire-only Divergences
  reported separately) and ADR-0008 (explicit idempotent installs, a
  pinned registry, Adapter DX as goal G6).
- Incident: a test's `git` calls under `git rebase -x` wrote into the
  shared repo config (`user.name=Test`, `core.bare=true`). Fixed, pinned
  by a test, and covered by new integration-safety rules in the
  tech-lead skill.
- Environment: this container's HTTPS proxy breaks Python 3.13 downloads
  from GitHub (strict X.509). Pumpkin is provisioned by hand with curl,
  sha256 pinned, until `mscts adapter install --from` exists.

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
