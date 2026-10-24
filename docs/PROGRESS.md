# Progress

Handoff between sessions. Update it at least every few commits and always
before stopping (see the `red-green` skill).

## Now

main: `mise run check` passes (1496 unit tests under
pytest-xdist, about 6 s); `mise run test:reference` passes (about 14
tests, 79–83 s under load) and `mise run test:candidate` passes.

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
- **G5 holds again** (reference tier 79–83 s under load): the Self-check
  reuses the session Reference as an Attached side. The margin is thin;
  Next item 1 parallelizes the tier.
- **M3a (installs): mostly done.** `mscts adapter install` installs
  the latest build for 26.3, or `<adapter>@<version>`, from where each
  Adapter says its builds are (#156; the Registry is gone), and
  `install/list/status` with `--from`, the build and its source recorded
  in SOURCE.json. `mise run test:candidate` passes. `install.require` asks on a TTY and otherwise fails naming the
  command; nothing installs inside a Run or test. `provision` is gone from
  the Adapter contract. The SessionStart hook runs `mise run
  install:reference` (explicit, loud). **M3a done** except M9's
  `adapter check`.
  Each Adapter is one folder, `src/mscts/adapters/<name>/`, with its
  tests in `tests/adapters/<name>/`; its import and its entry in
  `cli.py`'s `ADAPTERS` are the only lines outside it, and a unit test
  checks that (#155).
- **M3's first Report: done (session 3).** `uv run mscts run --candidate
  pumpkin [--scenario GLOB] [--repeat N]` plays the status Scenarios on
  vanilla and Pumpkin (about 10 s) and prints a text Report: observable
  Divergences by mechanic, wire-only per packet, Timings (`status.rtt`,
  `instance.startup`, median/p95), a legend. Live result: Pumpkin has no
  observable status Divergence; 4 wire-only (`description` as a
  component, a misspelt `enforceSecureChat`, `favicon: null`, `sample:
  []`), each pinned from the client jar
  (`docs/research/2026-09-26-comparison.md`). Report-path audit:
  `docs/audits/2026-09-26-report-path.md` (no high findings).
- **M3 (first Candidate):** `PumpkinAdapter.prepare` writes a
  native flat world save (DataVersion 4903) with the spec's seed and
  difficulty; a Bot joining Pumpkin lands in the Reference's flat world at
  y = -60 (candidate tier). Left: `mscts run` and the first Report (4).
- **ADR-0007 in code:** every Divergence is `observable` or `wire-only`
  (`Verdict.observable` for scores); the canonical table has the status
  declared defaults and the `update_tags` order, each cited from the
  client decoder.
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

Session 6 (2026-10-02, the project thread): the process moved to lanes and
review levels (PROCESS, changelog 2026-10-02). Every open issue has a
`lane:*` label; `docs/RISK.md` sets each lane's review level. The audit of
the timing and Compare code (reviewer, read-only) found 5 high bugs; fixes
filed as #114 and #116 (`lane:comparison`), #115 and #117 (`lane:timing`).
#114 goes before #30. Up to 5 agents at once.


Session 5 (goal: implement every `test` issue, #30–#72, with its enablers; at most
2 workers at a time):

- #22 is done in PR #122 (worker AV), not merged: the next tech lead reviews it. A
  join's window then matches 19 of 20 live; the 20th differs only in network traffic
  (a below-world sky section, empty vs zeros), which a Self-check still counts as a
  `mismatch`: #30 decides.

Session 5's lead stopped after #35 and #22 (maintainer). Open for the maintainer:
vanilla's tick-end resends and `section_blocks_update.blocks` are hash-ordered (a
canonical order in compare?); `mscts run` does not restart a stalled Candidate (Pumpkin
hangs on `fill ... destroy`); a Pumpkin Report is ~3.8 MB of join Divergences.

Next: the test Groups by the routine
(`.claude/skills/test-group`), simplest first. #30 `join/basic` waits for #22 (and #114).

Order: #18 (the barrier) → #17 (Control reuses it; ServerSpec refuses a view
distance over 12) → #23 tick-exact; #19 alongside. Then the output issues #12, #9,
#10, #14; #29, #21, #22, #24–#28; a text component enabler; the test-Group routine
skill; the tests by mechanic.

## Gameplay test catalogue (session 4)

58 issues from the 2026-09-30 survey (`docs/research/2026-09-30-gameplay-survey.md`):
15 `enabler` issues (#15–#29: schema package, Bot fidelity, Control, observation
windows, item stacks, entity schemas and renumbering, chunks and light, tick-exact,
statistical, Bot movement / blocks / entities / inventory, block event schemas) and 43
`test` issues (#30–#72). Build order and status: tracking issue #73. The decisions
on #18, #22 and #24 were taken in session 5 (see its log). Most issues also wait on
#7 and #8.

Session 3 direction (maintainer, 2026-09-26): one working end-to-end
command is the only goal. Next 4 (with the minimum of 3a it needs) is the
only feature work; Next 0 is shrunk to an audit of the code the Report
touches, afterwards; Next 1, 6, 11 and process work are parked. Lead
decisions for the Report: a mechanic is a Scenario id's first segment,
and wire-only Divergences are grouped per packet with a leaf count.

## Next

The queue is the open GitHub issues without `needs-triage`, `needs-decision`
or an open issue in a **Blocked by** line (ADR-0009).
New work goes there. The items below are migrated to issues as they are
picked up; until then, they are still the backlog.

Take the first item. Split it if it is more than one failing test. Keep
briefs at 3–6 increments and about 1500 lines at most.

0. **Audit (opus, read-only), re-brief worker Z.** The path from a
   Scenario to a Verdict: `compare.py` (observable vs wire-only, the
   canonical table, Masks), `scenario.py`, `scenarios/status.py`,
   `run.py` (Server/Attached sides, spec refusal, judge/blocked, H3b,
   Bot-named `failed`), the Bot/Connection failure paths, `install.py`,
   `registry.py`, `cli.py` (ADR-0008), `adapters/{pumpkin,nbt}.py`; plus
   an audit K re-check, a mutation sweep and one live run of each tier.
   Report in `docs/audits/2026-09-26-verdict-path.md` (format of audit
   K). The first Z was killed with only a skeleton. Hold feature work on
   these modules until its findings are in.
1. **`tooling` (sonnet), finish AA.** `scripts/time_tier.py` has landed
   (9d38c40). Left: the reference tier under `-n 2 --dist loadgroup`,
   the 30 s join keep-alive test in its own `xdist_group`, each xdist
   worker's session Reference on its own `free_endpoint()`; before/after
   tables from `time_tier.py`, target 55–65 s; a 5× repeat for flakes.

2. **Report follow-ups** (from audit AC): MD1 (`blocked` on a wire-only
   prerequisite), `--out DIR` (JSON/Markdown), a non-zero exit option,
   run order alternation for fair timings (M7), then `join/basic` (7) in
   the Report.

3a. `cli` (sonnet): Measurements are done (AB); left: `mscts selfcheck` over R's library `selfcheck`
    (Installations via `install.require` with the process's Terminal), and the first Measurements (`measure.py`: `status.rtt`,
    `instance.startup`). Split out of item 2 to keep R under 1500 lines
    and off S's `cli.py`.
4. ~~**M3's first Report**~~ (done, session 3; see Now) (opus, after V and 3a): `mscts run --candidate
   pumpkin` over the status Scenarios (then join), `report.py` with
   observable and wire-only sections (ADR-0007), grouped by mechanic
   (ADR-0006). Known Pumpkin Divergences to expect in play `login`:
   `is_flat=false`, `sea_level` 63 (vanilla -63), `enforces_secure_chat`
   true, `dimension_names` order. Decide grouping of per-leaf wire-only
   Divergences (a reordered `update_tags` gives one per leaf).
6. Research tooling (sonnet): `javap.py` (#5; libraries delegated as
   #6), `boot.py` and `join.py` are done. Left: netns sandbox, strace
   summary, a loopback-only reference test.
7. `join/basic` Scenario + Self-check 20/20, first checking that
   vanilla's `update_tags` order is stable across runs, with a spawn
   Fixture (`/setworldspawn`) per ADR-0006. The statistical
   `spawn/join-position` comes later (M6b).
8. Bot fidelity: send brand `custom_payload`, `client_information` and
   `player_loaded` as the vanilla client does; unique Bot names per
   Transcript (L11); dedupe the runner test helpers (L10).
9. ~~`runner`: a parent-death guard~~ (delegated: issue #3).
10. Tick research (opus, M6a) and statistical tier design (opus, M6b),
    per ADR-0006.
11. Tooling: ~~a check that every public name in `src/` appears in
    PLAN.md~~ (delegated: issue #4); a `scripts/` save/restore helper (no
    stash).

## Log

### 2026-10-24: train 43

- #491, #492, #494, #498, #499, #500 and #501 merged in three batches.
  #493 (#469) is held: its fix adds to the
  API a Group author writes against (`Bot.expect(since_ns=)`, and
  `observe` giving the time its window opened), so #469 waits for the
  maintainer (`needs-decision`). The integrator had stacked #494 on it,
  and the lead restacked #494 onto main without it (14 commits, each
  checked). Reference tier 36 of 36 on both tips.
- #494 (#41): four tick-exact hopper Groups, `redstone/hopper-transfer`,
  `-full`, `-pickup` and `-lock`, compare what each open container shows,
  step by step. Review B found two gaps where a hopper that retries every
  2, 3 or 6 ticks matched; both fixed. Pumpkin completes all four as
  `mismatch`: it opens no container set with items. `redstone/dropper-dispenser`
  moved to #490.
- #491 (#473): `combat/death` respawns through
  `_world.respawn_in_a_window`, which fails the Group when entity event 60
  comes before the respawn.
- #492 (#487): the lethal windows of `player/void`, `player/drowning` and
  `player/fall` close at a barrier after the death, so entity event 3 and
  the health the death leaves are compared.
- Filed #495 (Pumpkin 9c04f71 rewrites our `pumpkin.toml`; the candidate
  tier fails 1 of 15 on main), #496 (event 60 inside a lethal window's
  closing barrier), #497 (#41's lows, and a Pumpkin connection lost once
  each in three hopper Groups). Closed #463, fixed by #485.
- #498 (#495): the Pumpkin Adapter writes the config nightly 9c04f71
  knows, keeping Anvil storage (vanilla's format) where the build now
  defaults to its own. The candidate tier is 15 of 15 again.
- #499 (#472): `scripts/repeat.py` stops a series at its first failure and
  keeps that run's log, holds a deadline, stamps each line, and refuses a
  live selection under a Java the Reference refuses.
- #501 (#490): `redstone/dropper-dispenser`. A dropper fills a chest, one
  dispenser places water and picks it up, another equips an armor stand,
  each with a Bot holding its container open. Review B found that a
  dropper that never took the item out of its slot passed; fixed. A
  dispensed arrow is left to #46 (`entities/motion`): its `add_entity`
  velocity, yaw and pitch are random.
- #500 (#471): one test helper describes a mismatching play, with every
  Divergence and the timelines kept.

### 2026-10-23: train 42

- #466, #467, #468, #474, #475, #476, #482, #483, #484, #485 and #486 merged in
  stack order. Workers pushed branches and opened no PR; one integrator
  per batch stacked them, re-checked every commit and ran the tiers once
  on the tip (reference tier 36 of 36 on each; candidate tier 14 of 15 on
  the second, the failure #445's, and 15 of 15 on the third). Batch C
  failed when a worker ended without its StructuredOutput, and batch D2
  took over its issues.
- #466 (#454): `time/sleep` takes what its clock has already read before
  the sleeper lies down, so a `set_time` read with the clock's own barrier
  answer is not counted. 3 of 176 probe plays came up short on main under
  `-n 8 --stress`, 0 of 240 after.
- #467 (#461): `join/basic` calms the weather and waits for it to fade, so
  one Reference no longer rains after about 20 minutes.
- #468 (#456): a mismatching probe Self-check names each Divergence in its
  failure message. The 35-run stress series found no failure to read.
- #474 (#451): `registry_data` packets are paired by registry. Their order
  across registries is network traffic, shown once at `(order)`. Pumpkin's
  default run: 29 of 35 test cases pass against 27.
- #475 (#455): an element only the Candidate has reads `[→n]`, so no two
  Divergences of one pair of packets share a path. A Mask refuses a path
  with an arrow and names the one to write.
- #476 (#462): a recipe first seen outside the windows is named by what
  it shows, and a login ends every recipe name and number. A wrong later
  removal or group no longer passes. Review C found a false mismatch in
  the first fix, which a second round fixed.
- #482 (#445): the Pumpkin item-stack test names the nightly its table was
  recorded against, and the table is recorded again for 8ea2b7d.
- #483 (#442): titles for the seven `block_event` test cases.
- #484 (#441): `scripts/research/windows.py <group id>` plays a Group once
  on vanilla and prints each window's packets.
- #485 (#463): the respawn of `player/void`, `player/drowning` and
  `player/fall` fails the Group when entity event 60 comes before it
  (`Bot.respawn(fail_on=...)`), and `player/fall`'s lethal window ends on
  the death. Review C found the first fix made a late death a mismatch,
  which a third round fixed; `player/fall` 5 of 5 stress runs of 20.
- #486 (#464): `player/drowning` measures `drowning.bubbles_to_death`.
- Filed #469 (`time/sleep`: a `set_time` read between the window's open and
  the drain still counts), #470 (Groups that never stop the weather
  cycle), #471 (one description of a mismatching Self-check), #472
  (`repeat.py` stops a stress series at its first failure), #473
  (`combat/death`'s respawn can hold `entity_event` 60), #477 (a Mask
  refusal advises a path that cannot hide an arrow's Divergence), #478
  (the low findings #474 left), #479 (`_plain` raises RecursionError on a
  deeply nested display), #480 (a recipe named outside the windows,
  shorter than its JSON), #481 (recipe book entries read through the
  Masks before sorting), #487 (what a death sends after the kill packet
  is in no window) and #488 (a late Bot reads as a late Candidate in
  real-time checks).

### 2026-10-22: train 41

- #439, #433, #440, #450, #444, #453, #448, #452, #449, #459, #460,
  #458 and #457 merged one at a time, each after a checked rebase and
  the reference tier on its tip (36 of 36, except #452: 35 of 36, then
  the failed test 20 of 20 alone, filed #456). Workers ran in six
  Workflow batches.
- #440 (#39): six redstone Groups (repeater, comparator, torch,
  observer, dust, update order), each 20 of 20 in its Self-check.
- #450 (#146): shared test helpers moved to tests/support/; no
  `test_*.py` imports another.
- #444 (#436, #432): `player/fire` takes its step right after the first
  hit, so a late lava hit no longer fails it.
- #453 (#188): each Adapter installs its own builds through
  `Adapter.install(target, version, into, net)`, 7 lines for vanilla and
  6 for Pumpkin; mscts keeps the cache, SOURCE.json, the prompt and
  `--from`.
- #448 (#362): crafting compares the result slot after a take.
- #452 (#342): a status description's `extra` list is compared as the
  client reads it.
- #449 (#256): lists are lined up by edit distance, so a missing element
  shows as missing (Pumpkin's default run: 177,155 Divergences to
  5,720). Lists indexed by slot or position stay index by index.
- #459 (#438): the recipe book's button order is not compared; the
  research note says why.
- #460 (#443): a recipe group's number ends only at a compared packet
  that finds the group empty.
- #458 (#40): three piston Groups. #457 (#345): `player/drowning`
  compares the ticks between drowning hits.
- Filed #451, #454, #455, #456, #461, #462, #463 and #464.

### 2026-10-17: train 40

- #429, #430, #431, #434, #435 and #437 merged one at a time (reference
  tier 36 of 36 on each tip that needed it). The project paused at
  23:00Z with #439, #433, #440 and the fire branch open; train 41 took
  them over.
- #429 (#425): the research scripts read the installed vanilla jar
  through `install.installed()`.
- #430 (#423): each Self-check case carries its own pytest timeout;
  `player/starvation` gets 225 s a play (`SLOW_PLAY_LIMIT_S`).
- #431 (#427): a Bot operation's TimeoutError reads "<bot> waited
  <limit> s for <what>". `Bot.connect` still raises a bare one.
- #434 (#376): Pumpkin, like vanilla, answers `step_after`'s statistics
  request only after the action, 100 of 100 idle and under load. No
  barrier change.
- #435 (#426): the nine player Groups that use the environment or the
  arena clear the weather, stop its cycle and wait 100 game ticks for
  the rain to fade.
- #437 (#359): `Bot.swap_hands()` and `inventory/offhand`.
- Filed #432 (a unit test of `player/fire` failed under load), #436 (a
  late lava hit in `player/fire`), #438 (the recipe book's button order
  is not compared) and #441 (one command prints a Group's vanilla
  windows).

### 2026-10-17: train 39

- #416, #414 and #417 merged as one train (reference tier 36 of 36 on
  its tip), then #420 and #421 (36 of 36), then #422 (36 of 36,
  candidate tier 15 of 15), then #415 (36 of 36, Self-check tier 74 of
  74 on its tip). The train's per-commit check caught one red commit
  in #414 before it merged.
- #416 (#410): the repeater probe test timed out under load before its
  hang. It now uses a limit only the hang reaches and asserts the hang
  was reached. #421 (#419) did the same for three more tests and moved
  `HANG_LIMIT_S`, `STALL_S` and `late` to tests/group/test_control.py.
- #414 (#411): `scripts/repeat.py --live-lock` takes the live lock per
  run, so a short run waits for at most one run of a series (1.0 s
  against 9.1 s in `scripts/research/lock_wait.py`). A command run under
  a hold goes straight through (`MSCTS_LIVE_LOCK_HELD`). #420 (#418): a
  waiter interrupted before it has the lock no longer empties the
  holder's pid file.
- #417 (#412): `scripts/time_tier.py --rev A --rev B --rounds N` times
  a selection at two revisions, alternating, under one hold.
- #422 (#373): `add_transient_block` decodes field by field and its
  Divergences read "Falling block landing". Pumpkin never sends it.
- #415 (#356): an Observation window opens a nanosecond after the
  latest last barrier answer of a Bot besides Control, not after
  Control's; a frame read with that answer was lost before. An `until`
  window refuses a second Bot besides Control (per-Bot open Marks:
  #424). The player fake hurts at vanilla's period.
- Filed #418, #419, #423 (`player/starvation` overruns the 90 s a play),
  #424, #425 (`javap.py` downloads a cached jar), #426 (player Groups
  leave the weather cycle on) and #427 (a Group's TimeoutError always
  names the 10 s bound). Closed #383 (likely #403's cause).

### 2026-10-16: train 38

- #406, #407, #408 and #409 merged one after the other, each on the
  then-current main. Reference tier 36 of 36 on each rebased tip;
  statistical tier 7 of 7 on #409's.
- #406 (#403): the wrong side was blamed because the test told the
  Reference and the Candidate apart by port, and `free_endpoint` gives
  each Instance a random host, so two can share a port (about 1 in
  14 000). A test-only fix; no Verdict rule changed, so the lead lowered
  it from `scrutiny::high` to low. Likely the cause of #383 too.
- #407 (#402): Pumpkin's divergence, not a Bot bug. Pumpkin keeps one
  pending teleport and kicks an accept of an older id, which vanilla
  ignores (javap). The Bot accepts in order with the right ids, so the
  Report's `failed` Divergence stands and `mobs/*` keep failing against
  Pumpkin. Probe: `scripts/research/teleport_accept.py`.
- #408 (#396): `blocks/fill` drops four items per window and
  `inventory/give` compares `set_entity_data` in every window, 20 of 20
  each: #320's rule lifts both limits.
- #409 (#404): each `mobs/*` play calibrates its offset on the first
  `set_time` of its own step, and the 40-tick step is gone.
  `mobs/chase-open`'s stress Self-check went from 709 s to 570 s
  (median of three) of its 900 s limit.
- Filed #410 (a unit test failed once during a rebase), #411 (a stress
  series holds the live lock for hours, the fifth repeat) and #412 (a
  script to time a Self-check, main against a branch).

### 2026-10-16: train 37

- #397, #401, #398 and #400 merged one after the other, each on the
  then-current main. Reference tier: 35 of 35 on #397's, #401's and
  #398's branches, 36 of 36 on #400's rebased tip.
- #397 (#374): the live lock serves waiters in the order they asked,
  through a ticket queue under `<cache>/live-tier.queue/`; a waiter that
  dies drops out.
- #401 (#53): the sprinting hits compare `set_entity_data` (the sprint
  flag a hit clears), which #391's rule allows; `swing_animation` (new in
  26.3, sent only to players who see the swinger) is decoded and
  compared. Partial-charge hits stay out. #53 is closed.
- #398 (#387): each `mobs/*` play calibrates its Instance's time-query
  offset in a 40-tick step before the mobs are summoned and subtracts it;
  the play's Bot, an operator, reads the game time itself without
  waiting for the answer. Five stress Self-checks of `mobs/*`, 5 of 5;
  `mobs/chase-open` takes 707 to 716 s of its 900 s limit (#404).
  Against Pumpkin 0 of 13 pass (2 of 12 before), because of a Pumpkin
  kick right after the join (#402).
- #400 (#63): `time/advance`, `time/commands` and `time/sleep`, and a
  `set_time` schema. `time query gametime` is left out (#399, closed by
  the lead: the game time counts every tick since the world was made).
  Two reviews: 0 blocking, 3 high, all fixed. A stress run caught a
  `spawn_mobs` undo that turned spawning on for later plays. Against
  Pumpkin 18 of 101 test cases pass; Pumpkin never puts the sleeper to
  sleep.
- Filed #396 (#320's follow-up: Groups that leave out a second drop or
  `set_entity_data`), #402, #403 (a unit test once blamed the wrong side)
  and #404.

### 2026-10-15: train 36

- #392 (part of #53) merged first, then a train of #390, #393 and #391,
  then #394. On the train tip: reference 35 of 35, statistical tier 7 of
  7. Before #392: reference 35 of 35 on a stack with #390.
- #392: `combat/pvp-off`. In 26.3 `pvp` is a game rule, not a
  server.properties key. Pumpkin still hurts a player with it off.
- #390 (#388): a statistical Self-check that rejects only on
  `distribution` Divergences is played once more on two fresh Instances,
  and fails only if both reject (about 1 in 10,000 per Group).
- #393 (#384): `GroupContext.player_name` gives each Run its own player
  names; a rejected per-play count test shows the counts in the Report.
- #391 (#320): `section_blocks_update.blocks` is compared by position,
  and a run of resends for different entities by entity. A run ends at a
  window's end, at a tick Mark in a tick-exact Group, and at
  `add_entity`/`remove_entities`; uncompared packets go across it. Two
  reviews found the same blocking bug, the re-review a second; all fixed.
- #394 (#387): the time query adds 0 ticks to a `mobs/*` sample on
  vanilla and 1 on Pumpkin. The fix (calibrate per Instance) stays on
  #387.
- #63's `needs-decision` was dropped by the maintainer; it is next in
  #73's order.

### 2026-10-15: train 35

- #385 (#72) and #386 (#52), merged one after the other, each on the
  then-current main: reference 35 of 35 each time; statistical tier 2 of
  2 after #385, 7 of 7 after #386 (41 min).
- #385 (#72): `spawn/join-position` and `spawn/join-position-exact`, the
  first real statistical Groups. A new player is placed in the
  configuration phase (`PrepareSpawnTask.start`), so a play needs a fresh
  name, not a fresh world (docs/research/2026-10-15-spawn-position.md).
  Against Pumpkin the missing spread shows on `spawn.x`, `spawn.z` and
  `spawn.distance`; the exact Group matches.
- #386 (#52): `mobs/chase-open`, `mobs/chase-maze`, `mobs/doors-hard`,
  `mobs/doors-normal` and `mobs/targets`. Samples are tick counts read
  with `time query gametime` while the frozen world steps a fixed budget.
  Pumpkin completes with 2 of 12 test cases passing.
- Both at `scrutiny::medium` (the lead lowered #72 from high: no core
  change was needed). Filed #387 (a tick sample includes the time query's
  round trip) and #388 (the statistical tier fails by chance about 7% of
  runs).

### 2026-10-15: train 34

- Train 34 (#378, #380, #381, then #379), stacked in that order. On the
  train's tip every commit checked, reference 35 of 35, candidate 15 of 15.
- #379 (#24): `statistical` Groups. A statistical Group plays `runs` times
  per side (50 by default), the sides taking turns, and records named
  samples with `context.sample`. Each name is judged by a test (exact
  Kolmogorov–Smirnov conditional on ties; chi-square with pooling;
  Fisher's exact test or a seeded permutation test when pooling leaves
  too little), and so is its count per play, with Holm's correction at
  α = 0.01. `mscts run --statistical` plays them once per Run whatever
  `--repeat` says. The live `spawn/join-position` check moved to #72.
  Two reviews and a re-review found 4 blocking bugs, all fixed first.
- #381 (#347, #36): `blocks/dig-survival`. A STOP refused at the 0.7 check
  still breaks the block a tick later through the delayed destroy once the
  player has been alive long enough since its join or respawn
  (docs/research/2026-10-14-dig-finish.md). The Group is `exact`, timed
  by the clock, since a frozen world still ticks players. Five stress
  runs passed.
- #380 (#368): `_world.remove_tagged_until_gone` kills a Group's tagged
  entities and waits until a Bot beside them tracks only players; it
  never asks with `execute`, which Pumpkin lacks. Pumpkin still fails
  the entities Groups' clean-up: it drops loot with `mob_drops` off.
- #378 (#369): a live tier with its Installation missing fails before it
  waits for the live lock, and names the install command.

### 2026-10-14: train 33

- Train 33 (#371, then #372): `blocks/gravity` and `blocks/support` (#37);
  `fluids/water-spread`, `fluids/lava-spread`, `fluids/sources` and
  `fluids/interactions` (#38). The anvil falls one block, and falling-block
  movement is not compared: vanilla sends it on the entity tracker's clock,
  which runs in frozen ticks too. Each new Group passed its Self-check 20 of
  20. On the train's tip every commit checked, reference 35 of 35,
  candidate 15 of 15. Pumpkin fails every fluid Group on the flow itself.
- #367 (#360): `GroupContext.step_after` waits until the server has handled
  the acting Bot's packets (`Bot.wait_until_handled`, two statistics
  requests) before Control steps, at every act-then-step site in five Group
  families. Both reviews found nothing blocking; five stress runs per family
  passed; `player/fall` takes 81.3 s a play against 74.8 s on main.
- Filed: #373 (`add_transient_block` titles), #374 (the live lock is not
  first come, first served), #376 (measure the step proof on Pumpkin).

### 2026-10-11: train 32

- Train 32 (#365, then #366): `entities/summon`, `entities/data-changes`
  and `entities/death` (#43); `entities/item-merge`,
  `entities/item-despawn` and `entities/item-pickup` (#47). Experience
  orb merging is not compared: vanilla's depends on entity ids. Each new
  Group passed its Self-check 20 of 20. On the train's tip every commit
  checked, reference 35 of 35, candidate 15 of 15, the entities
  Self-checks 6 of 6.
- #360's barrier (PR #367, draft) is not merged: `GroupContext.step_after`
  passed five stress runs for inventory, movement, blocks and combat, but
  `player/fall` overran the Self-check's 90 s a play. The next lead
  chooses the lighter one-request proof or leaving `player/fall` out.
- Filed: #368 (`remove_tagged` and bodies; Pumpkin keeps the tagged
  entities), #369 (the SessionStart hook does not install Pumpkin).
- Paused after this train at Eric's request (2026-10-10 18:53Z).

### 2026-10-10: train 31

- #357 (#350): Group test modules play each Group once per process, and the
  unit tier runs `--dist loadfile`. The tier went from 9 min 35 s to about
  3 min under `mise run check`.
- Train 31 (#358, then #361): `inventory/give`, `inventory/clicks-inventory`,
  `inventory/clicks-chest` and `inventory/drop` (#61); `crafting/grid`,
  `crafting/recipe-book` and `crafting/unlocking` (#62), with the recipe
  book packets decoded and `Bot.place_recipe`. Each new Group passed its
  Self-check 20 of 20. Reference 35 of 35, candidate 15 of 15, and the
  inventory, crafting and join Self-checks on the train's tip.
- Left for follow-ups: the off-hand swap (#359), a barrier between a Bot's
  action and `tick step` (#360), taking a crafting result (#362), and
  renumbering recipe display ids instead of masking them (#363).

### 2026-10-10: train 30

- Train 30 (#348, #353, #351, then #352): the review results table in
  `docs/RISK.md`; `combat/damage-types`, `combat/armor`, `combat/effects`
  and `combat/death` (#54); `player/game-modes`, `player/death` and
  `player/respawn` (#59); `player/regeneration`, `player/starvation`,
  `player/eating` and `player/exhaustion` (#57). Shared Group helpers moved
  to `groups/_world.py`. Reference 35 of 35, candidate 15 of 15, and the
  player, combat and chunks Self-checks on each tip.
- `combat/armor` and `combat/effects` play fewer kinds of damage than #54
  lists, to fit the Self-check's 90 s play. `player/exhaustion` has no jumps
  (#354), and the hunger Groups compare the order of changes, not their tick.
- Filed: #350 (the unit tier takes 20 minutes serially), #354.

### 2026-10-09: train 29

- #340 (#326): `mise run commit` works on a shallow checkout.
- Train 29 (#339, #341, #343, #346, #344): the scrutiny nudge replaces the
  area levels; a test case only network traffic names is never scored and
  shows as `·` (#330); `blocks/dig-creative`, `blocks/place` and
  `blocks/place-attached` (part of #36; `blocks/dig-survival` waits on
  #347); six `combat/*` Groups (part of #53); six `player/*` Groups
  (#56). Reference 35 of 35 and candidate 15 of 15 on its tip.
- Filed from reviews: #342 (status `description` with `"extra": []`),
  #345 (how often environment damage repeats), #347 (why vanilla accepts
  an early dig finish from a player that has been in a while).

### 2026-10-04 to 2026-10-07: trains 22 to 28

The project paused after v0.1.0 (released 2026-10-04 from 9cdf1ed) and
resumed on 2026-10-07. Since then a lead hands off to a fresh session
after each chunk of work.

- Train 22 (#277, #287, #304), train 23 (#288, #289, #299, #308, #294,
  #280, #292, #271) and train 24 (#310, #276, #279, #281) landed v0.1.0's
  last work on 2026-10-04.
- Train 25 (#314 to #317, #236, #232, #253) and train 26 (#324, #243,
  #307, #305, #306, #322) closed #293, #303, #300 and #319 and merged the
  helper's seven PRs. Reference 35 of 35 on train 26's tip.
- Train 27 (#325, #327, #328, #329, #332): the `test_live_lock` signal
  flakes are gone (#295, #224: `sigwait`, 200 of 200 under stress); a
  Candidate without `/tick` no longer reads as frozen (#290); container
  test cases have titles and `state_id` is network traffic (#283); Groups
  avoid Pumpkin's malformed item components (#312); the helper agent is
  retired. Candidate 15 of 15, reference 35 of 35 on its tip.
- Train 28 (#333): `movement/invalid` and `Bot.move_unchecked` (#278).
- Filed from reviews: #330 (a network-traffic-only field changes the
  Score), #331 (titles under structured item components), #334
  (Divergences from windows a Candidate never played), #335 (kick reasons
  compared byte for byte), #326 (`mise run commit` on a shallow checkout).

### 2026-09-30 — session 5: building the test catalogue

Maintainer goal: implement every test issue from session 4, at most 2 parallel
workers, about 1.5 opus sessions per issue on average, one consistent architecture
(no hack on hack; a refactor only when failures repeat).

- Merged #74 (the catalogue and the test proposal framework), #75 (#15: play
  schemas are a package, one module per mechanic) and #76 (#7: Scenario is now
  Group everywhere; the lead renamed it in the skills) and #77 (#11: the kinds of
  difference are gameplay and network traffic) and #78 (#8: every compared field
  is a test case named `<packet>.<path>`, e.g. `status_response.description`).
- A usage limit, then a container restart, stopped AF (#20) and AH (#8); both
  were resumed by message with their worktrees intact.
- Lead decisions under the maintainer's delegation, recorded on each issue and
  reversible by the maintainer: #11 the kinds are **gameplay** and **network
  traffic**; #18 observation windows (option 1); #22 compare chunks as the client
  ends up seeing them (option 1); #24 the recommended tests plus Holm–Bonferroni
  across a Group's sample names, and one Reference-vs-Reference Self-check that
  must not reject.
- Merged #79 (#16: the Bot sends brand, client information and `player_loaded`
  as the vanilla client does; decision: ServerSpec refuses a view distance over
  12, landing with #17) and #80 (#20: 25 entity packet schemas; entity ids are an
  `EntityId` wire type so #21 finds them by type; an item stack is refused until
  #19, which runs next).
- #18 runs before #17: both need a barrier (a round trip the server answers only
  after everything caused before it), built once as `Bot.sync()`.
- Merged #81 (#18: a Group compares only the play packets inside its Observation
  windows; the barrier is two statistics round trips; ADR-0010). Its Pumpkin test
  is an expected failure until #19. Found: every join differs between two vanilla
  Instances (`session_id`, `update_tags` order), now a shared rule in #17.
- The output lane (#14, #12, #9, #10, #13) went to the maintainer's helper agent,
  with lead decisions on #9, #10, #12 and #14.
- Merged #82 (#19: every item stack vanilla sends decodes strictly; 122 data
  components from a generated name list; `codec/shapes.py` holds the shapes they
  share; hashing moved to #28). Pumpkin sends 18 of the giveable stacks in a form
  that does not decode, and its `/give` parser hangs a thread for good on a
  component name with a slash. Filed #83: a failing tier test shows each
  Instance's console tail.
- Merged #85 (#17: Control runs a command, then a `tellraw` marker, and waits
  for the marker before the barrier; 440 Self-check plays without a failure).
  Pumpkin answers commands out of order. Filed #84 (one Self-check tier driven by
  the registry), because G5 is broken: check 11–18 s, reference tier 147–303 s.
- Merged #87 (#29: block and world event schemas; the sound seeds are random
  fields; a random pitch is a Group's own Mask, never a global one). Pumpkin's
  block and world events all decode. Filed #88: under load a watcher can miss a
  `block_update` in a chunk it has not received yet.
- Merged #86 (#83: a failing server-tier test shows each Instance's console tail).
- #88 re-scoped after AO's research disproved the lead's chunk hypothesis: under
  load vanilla can answer both statistics round trips in one pass, before the
  tick's block updates. The fix is a gap-checked `Bot.sync()`; ADR-0010 is amended.
- Merged #96 (#84: `mise run test:selfcheck` gives every registered Group a
  Self-check on two shared Instances, 18–31 s; the reference tier is still 210–259 s).
  A join's repeated `player_position` is a race with the server's first tick (javap
  account in `docs/research/2026-09-26-join.md`), so only its pose is asserted.
  Filed #97 (a Group sees the previous Group's Bots) and #98 (helper).
- Merged #99 (#88: `Bot.sync()` ends only when a pair of statistics answers arrive a
  tick apart, at least 5 ms; capped at six requests with a `sync:capped` Mark; 884
  probe plays under load with no mismatch). Pumpkin answers a pair 50 ms apart.
- Merged #121 (#35: `blocks/setblock`, `blocks/fill`, `blocks/clone`, a `builder` operator
  Bot runs each command in its own window; 20 of 20 Self-checks; the first full run of the
  test-group routine, which it corrected). PRs now land with a merge commit.
- Merged #113 (#106: login's dimension names, attributes, recipes and advancements sorted
  as the client keys them; `update_recipes` and `update_advancements` decode; a Mask hides a
  value, never whether it is there (`compare.MASKED`), and `[*]` is every index; `obtained`
  is a clock value in `RANDOM_FIELDS`). A join's window now differs only in its chunks (#22).
- Merged #112 (#105: `observe(until=<packet>)` ends a window at that packet's arrival, no
  barrier; frames of one socket read are stamped a nanosecond apart; `Control.leave()`;
  a join's window held the same packets on two vanilla Instances in 160 of 160 plays).
- Merged the helper's #110 (#107: probe_loop saves whole payloads, prints totals per
  test case, exits 0, takes `run(loop=...)`; javap `--out DIR`) and #111 (#109: the
  docs checks run the guide's Python examples; a fragment carries `<!-- not run: why -->`).
- Merged #108 (#21: each Bot's entities are numbered `#1`, `#2`, ... in the order the
  compared packets first name them, so entity ids and mobs' UUIDs need no Mask, and a
  Mask on an entity id is refused; a pig-summoning Group self-checks 20 of 20 five times).
- #30 measured (worker AR): two vanilla joins matched in 2 of 84 plays, for six causes
  traced by javap (hash-ordered lists, a clock value, chunk order, light encoding, the
  barrier letting later batches and mobs in). Filed #105, #106, #107 and a #22 addition;
  the test-group skill now starts every test issue with that measurement.
- Merged #104 (#97: before each Group the Run polls status until no player is online,
  `mscts.settle`; a Candidate that never empties is a `mismatch`). Vanilla drops a closed
  Bot within 10–197 ms (`docs/research/2026-10-02-settle.md`).
- Merged the helper's PRs #100 (#4: `mise run plan`, every public name is in PLAN), #102
  (#3: the next launch sweeps orphaned Instance groups) and #103 (#98: `time_tier.py`
  fails with its command).
- Merged the helper's (ChatGPT) PRs: #91 (#14 docs drift checks), #92 (#12 test
  case titles), #93 (#9 the short default Report, ADR-0012), #94 (#10
  `--verbose`), #95 (#13 the home page's real Report) and #89 (#6 javap `--lib`).

### 2026-09-30 — session 4: what to test between servers

Maintainer goal: explore what mscts should compare (lighting, spawning, combat, mob
simulation, chunk loading, …), make adding a test a standard process, and file the
tests as issues that independent agents can take. No worker was spawned.

- Environment: `mise run check` (1549 tests), the reference tier (14 tests, 112 s)
  and the candidate tier (8 tests) all pass. The Pumpkin nightly moved: sha256
  `b8382a8af2afd0a2cab48133ed335a436a771f813823a39b8b2b9c68a2dd360e` (126,447,960
  bytes), installed with `--from`; it matches no Registry entry, so pinning it is
  the maintainer's call.
- Live probe, vanilla vs Pumpkin, as an operator Bot: both have `/tick`; the join
  order, the first chunk batch (9 vs 1), the `commands` tree (265 vs 19,578 bytes
  for a non-operator), chunk light, and the packets of `/damage`, `/give`,
  `/effect`, `/gamemode`, `/summon` and weather under a frozen world all differ.
- javap: 26.3 light masks are a byte-array BitSet (`ByteBufCodecs$15`), not the
  wiki's longs. Game rules are snake_case (`advance_time`, `respawn_radius`, …).
- Framework: the `test` issue template, "Proposing a test" in
  `docs/contributing.md`, `test` / `enabler` labels (PROCESS changelog).
- Filed #15–#72 and the tracking issue #73.

### 2026-09-26 — session 3: the first end-to-end Report

Maintainer goal: one working command. Two workers (AB, AC), both opus.

- Local `main` was stale again; saved as `backup/stale-local-main-2`.
  Pumpkin re-curl'd (same sha256 pin) and installed with `--from`.
- Worker AB: `measure.py`, `run.run_results` (Measurements per
  repetition, `instance.startup`, status versions), `report.py`, `mscts
  run`, a candidate-tier CLI test.
- Lead: `status/ping` requires nothing (it was blocked on Pumpkin, so no
  rtt); wire-only examples say "and N more"; the summary says plainly
  when no difference is one a player would notice.
- Worker AC: from the client jar, the status codec reads only its five
  named keys and DFU's JsonOps reads a JSON `null` as absent, so both
  Pumpkin "observable" status Divergences were wire-only; status JSON is
  now compared at JSON paths. Report-path audit, no high findings.
- Parked by the maintainer: Next 0 (full audit), 1, 6, 11, process work.

### 2026-09-26 — session 2: new tech lead

Workers Q–Y and AA ran (V twice), one helper PR (#5) was merged, and two
API rate limits killed in-flight workers (T, U, V; then Z, Y, AA).

- Local `main` held a stale pre-rewrite history; saved as the local
  branch `backup/stale-local-main` and reset to `origin/main`.
- Worker Q: the unit tier runs under pytest-xdist (`-n auto`), 11.5 s →
  about 5 s, so G5 holds again. `scripts/repeat.py` flake-hunts under CPU
  stress; 25 stressed runs found no flakes, so the integration retry is
  gone.
- Worker Y: `scripts/research/boot.py` and `join.py` (research
  harness); the chunk decoder moved to `scripts/research/chunkformat.py`.
- Worker AA (interrupted): `scripts/time_tier.py` only.
- Worker W: a Run side can be an `Attached` Instance; the Self-check
  reuses the session Reference (G5 back under 90 s); a `failed`
  Divergence names its Bot (G3).
- Worker X: `mise run commit` (the only way to commit), `strays.py
  --token/--cwd`, `mutate.py --batch` with untracked files.
- Worker V: observable vs wire-only Divergences; status declared
  defaults and `update_tags` order in the canonical table.
- Helper PR #5 (Astra): `scripts/research/javap.py`; the lead added the
  version-JSON sha1 check and rebase-merged it.
- Worker U: a strict NBT writer; Pumpkin writes a native flat world save
  with the spec's difficulty; the first chunks match the Reference's.
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
