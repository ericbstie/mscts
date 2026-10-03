# Risk register

Owned by the tech lead. It sets how hard each change is reviewed
([PROCESS](PROCESS.md#lanes-and-review-levels)), so the review level is a
rule kept here, not a feeling.

## Levels now

Each area has a scrutiny level. An issue's `scrutiny::*` label is the
highest level of the areas it will touch, raised one step for new
concurrency, a new kind of Verdict, or code later Groups build on (the
lead's triage; [PROCESS](PROCESS.md#lanes-and-review-levels) says what
each level requires).

| Area | Files | Level | Clean merges since the last escape | Why |
| --- | --- | --- | --- | --- |
| timing core | `net.py`, `bot.py`, `settle.py`, `group.py`, `transcript.py` | high | 1 | Five escapes since 2026-09-26, then audit 2026-10-02 H1, H5 (`docs/audits/2026-10-02-timing-compare.md`); a socket leak on cancel since (#127; #133 turned out not to leak). The audit these call is folded into the reviews of #115 (PR #163, merged) and #117 (PR #179) |
| comparison core | `compare.py`, `measure.py`, `test_cases.py`, `codec/entity_ids.py`, Verdicts in `run.py` | high | 3 | Audit 2026-10-02 H2, H3, H4; vanilla's own chunk encodings read as Divergences (#172, found by #30's measurement). The independent review of PR #173 stood in for the audit |
| codec | `codec/*` | medium | 0 | Audit K MD1, MD4 (2026-09-26); none since |
| platform | `runner.py`, `adapters/*`, `install.py`, `registry.py`, `spec.py`, `cli.py`, `report.py` | medium | 1 | Audit K H1; orphaned Instances (#3) |
| Groups | `groups/*`, `tests/group/*` | high | 1 | Raised 2026-10-03: `blocks/clone` gave `mismatch` on vanilla against vanilla (#170) |
| tooling and docs | `scripts/*`, `docs/*`, `.github/*`, test fakes | medium | 2 | Raised 2026-10-03: flaky probe test (#123), fake server hang (#126), `commit_green` let a ty-red commit through (#150) |

Tick-exact and statistical Groups are raised to high: they rest on the
timing core and on statistics that are new ground.

## Rules

- **An escape raises the level.** A bug found on `main` (by a later
  issue, a tier run, an audit or a user) raises its area one level, resets
  its clean count, and the lead relabels that area's open issues.
- **Clean merges lower it.** After 5 merges in a row in an area with no
  escape, its level drops one step, to low at the lowest.
- **An escape at high calls an audit** of that area, briefed to the
  reviewer.
- A bug caught before merge (by review, a Self-check, a mutation sweep) is
  logged below but raises nothing: that is the review working.

## Bug log

Newest first. "Escaped" means it was on `main`.

| Date | Area | Bug | Found by | Escaped | Follow-up |
| --- | --- | --- | --- | --- | --- |
| 2026-10-03 | core: timing | A kick drained quietly after the barrier made later windows skip that Bot (`mismatch` became `match`); a Bot that joined after a window stayed inside it (#179 review H1, H2) | review | no | fixed before merge |
| 2026-10-03 | Groups | `join/basic` turned regeneration back on while its player was online, so saved saturation drifted: 18 of 40 Self-check plays mismatched (#176 review) | review | no | fixed before merge |
| 2026-10-03 | Groups | `blocks/clone` Self-check mismatched: the builder's random spawn put it under a cloned block on one Instance only, so it crawled and choked there | Self-check | yes | #170 (PR #180) |
| 2026-10-03 | core: comparison | Sorting an over-long hash palette spilled indexes: a false gameplay mismatch, or an `OverflowError` that ended the Run (#173 review) | review | no | fixed before merge; any exception from compare is now `error` (#174, PR #177) |
| 2026-10-03 | core: comparison | Two chunk encodings vanilla varies between its own runs (palette order, empty or zero sky light below the world) read as Divergences | #30's measurement | yes | fixed in #173 |
| 2026-10-03 | core: comparison | Chunk reordering not canonical: a neutral packet before a run's first chunk stayed put but one after it moved behind the chunks, a false gameplay mismatch possible between two vanilla joins (#122 re-review 1) | review | no | fixed before merge |
| 2026-10-03 | core: comparison | Entity naming gaps: an id first seen in a remove was compared raw, fully masked names collided, a `*` Mask on add_entity was ignored (#140 re-review N1-N3) | review | no | fixed before merge |
| 2026-10-03 | core: comparison | A Candidate that reuses an entity id without removing it first keeps the first name, so the new entity is compared under the old name (#140 re-review N4) | review | no | known limit, no fix planned |
| 2026-10-03 | core: comparison | Pre-window entities named by raw or random position: a Mask could not reach the name, and players were named by their random join position (#140 reviews H1, M1, ordering 1-2) | review | no | fixed before merge |
| 2026-10-03 | core: timing | `test_connection.py` last-arrival test failed once under `-n auto` | #122's worker | yes | #149 |
| 2026-10-03 | tooling and docs | `commit_green` let a commit that `ty` rejects through | #122's worker | yes | #150 |
| 2026-10-02 | core: comparison | Chunks reordered across `light_update` and `forget_level_chunk` (#122 ordering review, high) | review | no | fixed before merge |
| 2026-10-02 | core: comparison | A harness bug in the Candidate's settle wait counted as the Candidate's `mismatch` (#128 reviews) | review | no | fixed before merge |
| 2026-10-02 | core: timing | Cancelling a Run mid settle wait can leak a poll's socket: not a bug, a test now shows no socket is left open at any cancel point | #128's review | no | #133 (PR #159) |
| 2026-10-02 | core: timing | A second cancel during `Connection.close` leaked the socket | timing specialist (#123) | yes | fixed in #132 |
| 2026-10-02 | tooling and docs | The fake server hung on a client that gave up connecting | timing specialist (#123) | yes | fixed in #135 |
| 2026-10-02 | tooling and docs | A cancelled-probe unit test failed 4 in 50 under stress | flake hunt | yes | fixed in #125 |
| 2026-10-02 | not yet known | Self-check `blocks/fill` mismatched, and `blocks/setblock` timed out, once each under heavy load | Self-check under stress | yes | #129, #134 |
| 2026-10-02 | core: timing | A stall in the harness looks like a server tick to `Bot.sync` (audit H1) | audit | yes | fixed in #163 |
| 2026-10-02 | core: timing | One unrequested `award_stats` shifts every later barrier answer (audit H5) | audit | yes | fixed in #163; a stray held back by TCP flow control still counts (#169) |
| 2026-10-02 | core: comparison | Entity numbering hides an action on the wrong entity spawned before the window (audit H2, from #108) | audit | yes | #116 |
| 2026-10-02 | core: comparison | Candidate status JSON can crash the Run or give `error` (audit H3) | audit | yes | #114 |
| 2026-10-02 | core: comparison | `PlayersStillOnline` inside a Group is `error`, not `mismatch` (audit H4) | audit | yes | #114 |
| 2026-10-02 | core: comparison | Window names unchecked; one close Mark for every Bot (audit MD1, MD2) | audit | yes | #117 |
| 2026-10-02 | core: timing | The frames of one socket read shared an arrival stamp | #105's worker | yes | fixed in #112 |
| 2026-10-02 | core: timing | Under load vanilla answered both barrier requests in one pass (1 in 200) | #88's worker | yes | fixed in #99 |
| 2026-10-02 | core: comparison | A join differs between two vanilla Instances for six reasons (hash order, a clock value, chunks) | #30's measurement | yes | #105, #106, #22 |
| 2026-10-02 | core: platform | A Group saw the previous Group's Bots still online | #84's worker | yes | fixed in #104 |
| 2026-10-02 | core: timing | A status poll cancelled from outside leaked its socket | mutation sweep (#97) | no | fixed before merge |
| 2026-10-02 | tooling and docs | Two unit tests' timing margins failed under load | flake hunt | yes | fixed in 0340581 |
| 2026-10-01 | core: timing | `Bot.sync()` was no barrier behind a command (8 of 80 plays) | #17's worker | yes | fixed in #85 |
| 2026-09-26 | core: platform | Readiness accepted any server answering at the Endpoint (audit K H1) | audit | yes | fixed |
| 2026-09-26 | core: timing | Received stamps were take time, not arrival time (audit K H2) | audit | yes | fixed |
| 2026-09-26 | core: comparison | A Candidate's undecodable packet had no Verdict (audit K H3) | audit | yes | fixed |
