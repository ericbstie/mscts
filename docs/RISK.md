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
| timing core | `net.py`, `bot.py`, `settle.py`, `group.py`, `transcript.py` | medium | 4 | Audits 2026-09-26 and 2026-10-02 (H1, H5), then escapes #127, #184 and #169: an unasked `award_stats` could end a barrier a pass early (found in the review of PR #163 and left for later; fixed in #218). Lowered 2026-10-03 after 5 clean merges (#204, #220, #218, #223, #231). Clean since: #248, #264, #265, #267 |
| comparison core | `compare.py`, `measure.py`, `case_titles.py`, `codec/entity_ids.py`, Verdicts in `run.py` | high | 2 | Audit 2026-10-02 H2, H3, H4; #172. Lowered 2026-10-03 after #226, then raised by #239 the same minute. Five escapes in the Score and the Report: a Candidate failure scored too lightly (#239, #230, #262), a prerequisite that differed only in network traffic blocked its dependents (#221), and an 88 MB `report.json` (#254). Lowered 2026-10-04 after #223, #231, #234, #250, #258, then raised by #266 (open). Clean since: #267, #268 |
| codec | `codec/*` | medium | 4 | Audit K MD1, MD4 (2026-09-26); none since. Clean since: #220, #250, #248, #265 |
| platform | `runner.py`, `adapters/*`, `install.py`, `spec.py`, `cli.py`, `report.py` | low | 2 | Audit K H1; orphaned Instances (#3); mobs near the Fixture world's spawn (#183). Lowered to medium 2026-10-03 after #192, #194, #158, #204, #205, and to low 2026-10-04 after #219, #227, #214, #223, #258. Clean since: #261, #263 |
| Groups | `groups/*`, `tests/group/*` | high | 3 | `blocks/clone` (#170). Lowered 2026-10-03 after 5 clean merges (the last #216, #235, #218). Raised 2026-10-04: a random tick turned the grass under the tick-exact probe's redstone block to dirt on one Instance (#272). Clean since: #250, #275, #267 |
| tooling and docs | `scripts/*`, `docs/*`, `.github/*`, test fakes and helpers | low | 1 | Raised to high 2026-10-03: stress runs on `main` found two flaky unit tests (#209, #210) and an untested signal path (#211); then two test races (#233, #246) and a test helper that read windows by index (#249). Lowered to medium 2026-10-03 after #235, #226, #218, #245, #241, and to low 2026-10-04 after #247, #251, #223, #257, #275. Clean since: #274 |

Tick-exact and statistical Groups are raised to high: they rest on the
timing core and on statistics that are new ground.

A merge counts for an area when it changes that area's files. The docs
and stored samples that every PR updates (ADR-0009) do not count for
tooling and docs. A bug that a review finds and the same merge train
fixes was caught before merge. A bug left for a later train was on
`main`, so it escaped.

Audits owed (an escape at high):

- timing core: called by #169.
- comparison core: called by #221, then #230, #262 and #254.
- tooling and docs: called by #210, then #211, #233, #246 and #249
  (#209 had raised it to high).

Process gaps in trains 14 to 21:

- Trains 14 to 21 merged with this register not updated. This update
  covers them.
- The high-scrutiny PRs #263, #264, #265, #271, #269 and #277 got one
  review each. PROCESS requires two.
- #65, #60 and #270 were labelled medium, though they touch high areas.
  They were relabelled high on 2026-10-04.

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
| 2026-10-04 | Groups | A random tick turned the grass under the tick-exact probe's redstone block to dirt on one Instance only: a false `mismatch` in 1 of 20 plays (#272) | train 20's reference tier | yes | fixed in #275 |
| 2026-10-04 | tooling and docs | #268's stored Report sample went stale once #260 recaptured it | train 21's checks | no | re-rendered in #268 before merge |
| 2026-10-04 | core: comparison | #258's rule that a `bot` or `failed` Divergence is never network traffic broke #260's test, which built one | train 20's checks of each commit | no | fixed in #260 before merge |
| 2026-10-03 | core: comparison | A Candidate left unsettled fails each later Group as one line, not as its test cases, so it can score above one that sends every value wrong (#266) | review of PR #263, left for later | yes | open |
| 2026-10-03 | core: comparison | A Candidate failure of a whole Group (it raised, was left unusable, or made the Comparison raise) failed one line, not each test case of the Group (#262) | review of PR #259; on `main` since #237 | yes | fixed in #263 |
| 2026-10-03 | core: comparison | A default Run against Pumpkin wrote an 88 MB `report.json` (#254) | #32's worker, left for later | yes | fixed in #260 |
| 2026-10-03 | tooling and docs | Test helpers read a window as the events after an index, so another Bot's later packets could move in or out of it (#249) | #26's worker | yes | fixed in #251 |
| 2026-10-03 | tooling and docs | A `test_bot_sync` test raced the transport's read (#246) | macOS check on PR #240 | yes | fixed in #247 |
| 2026-10-03 | core: platform | The macOS check job failed on every PR (#143, #144). Not counted: mscts runs on Linux only so far, and the job was allowed to fail | CI | no | job switched off in #245; #143, #144 open |
| 2026-10-03 | core: comparison | A Candidate value that made the Comparison raise gave `error`, which the Score leaves out (#239) | review of PR #237, left for later | yes | fixed in #259 |
| 2026-10-03 | tooling and docs | A fake kicked whichever Bot asked first, not the second to join (#233; #252 is the same) | macOS check on PR #220 | yes | fixed in #235 |
| 2026-10-03 | core: comparison | A Candidate packet that failed to decode scored one test case, not one per field of the Reference's packet (#230) | review of PR #227, left for later | yes | fixed in #261 |
| 2026-10-03 | core: comparison | Tick-exact: when the first of two copies was missing, the Report blamed the second (#229) | review of PR #223 | no | fixed in #234, in the same train |
| 2026-10-03 | core: timing | A Reference left frozen after a failed Group would make later Groups blame the Candidate (#228) | review of PR #223 | no | fixed in #231, in the same train |
| 2026-10-03 | core: comparison | Replacing or leaving out a compound field failed one test case, not one per field it holds (#225) | review of PR #219 | no | fixed in #227, in the same train |
| 2026-10-03 | core: comparison | A Group that raised an unexpected exception on the Candidate's value gave `error`, which the Score leaves out (#222) | review of PR #219 | no | fixed in #237, in the same train |
| 2026-10-03 | core: comparison | A prerequisite that differed only in network traffic blocked its dependents (#221) | review of PR #219, left for later | yes | fixed in #258 |
| 2026-10-03 | core: timing | A Group that kept `bot.entities` across a login or a respawn into another dimension still saw the old level's entities (#264 review M1) | review | no | fixed before merge |
| 2026-10-03 | Groups | `players/join-seen` did not wait until Control had left, so ada's window could catch its removal (#250 review) | review | no | fixed before merge |
| 2026-10-03 | tooling and docs | #218's strict xfail passed under load: the fake's timing let the barrier hold | train 19's checks | no | fixed in #218 before merge |
| 2026-10-03 | tooling and docs | No test covered a signal that reaches `live_lock` before its command starts (#211) | mutation run on PR #208, left for later | yes | fixed in #241 |
| 2026-10-03 | tooling and docs | A `test_bot_sync` test failed 2 in 20 under stress (#210) | stress run on `main` | yes | fixed in #217 |
| 2026-10-03 | tooling and docs | Three `blocks/clone` unit tests failed in 7 of 20 runs under stress: the fake's time limit for one exchange ended a whole play (#209) | stress run on `main` | yes | fixed in #216 |
| 2026-10-03 | not yet known | A Self-check failed once on #158's head; the train script kept no log (#207) | train 14's Self-check | yes | #207 open; trains keep full logs since |
| 2026-10-03 | core: timing | An unasked `award_stats` after a sync request could end the barrier a pass early (#169) | review of PR #163, left for later | yes | fixed in #218; two in one sync still can (a strict xfail) |
| 2026-10-03 | core: timing | A disconnect still queued when a Group ended gave `match`: the end never looked for it (#184) | lead | yes | fixed in #189 |
| 2026-10-03 | core: platform | Mobs spawned near the Fixture world's spawn; their sounds reached a joining player before any chunks, on one Instance only, a false `mismatch` (#183) | reference tier flake, cause found by the timing specialist | yes | #199 (one probe), #200 (every Group) |
| 2026-10-03 | tooling and docs | Two live-lock unit tests (signals, killed wrapper) failed once each under load (#171) | check runs during #122 and #189 rebases | yes | #171 |
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
| 2026-10-02 | core: comparison | A harness bug in the Candidate's settle wait counted as the Candidate's `mismatch` (#128 reviews) | review | no | fixed before merge; #222 deliberately reverses it: any exception on the Candidate alone is its `mismatch` |
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
