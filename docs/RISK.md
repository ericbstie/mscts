# Risk register

Owned by the tech lead. It names the core areas the
[scrutiny nudge](PROCESS.md#lanes-and-review-levels) refers to, and logs every
bug found so the escape statistics can be redone.

## Areas

| Area | Files |
| --- | --- |
| timing core | `net.py`, `bot.py`, `settle.py`, `group.py`, `transcript.py` |
| comparison core | `compare.py`, `measure.py`, `case_titles.py`, `codec/entity_ids.py`, `report_json.py`, Verdicts in `run.py` |
| codec | `codec/*` |
| platform | `runner.py`, `adapters/*`, `install.py`, `spec.py`, `cli.py`, `report.py` |
| Groups | `groups/*`, `tests/group/*` |
| tooling and docs | `scripts/*`, `docs/*`, `.github/*`, test fakes and helpers |

## Escapes

An escape is a bug that reached `main` in a merged PR and was found after
that PR merged. It belongs to the PR that introduced it, however late it is
found: an audit that turns up a bug from an old PR records an escape of
that old PR. A bug that a review, a Self-check, a stress run or a mutation
sweep found before the merge was caught, even when the lead left its fix for
a later PR. It is logged here with Escaped "no, deferred to #<n>".

Log every bug found, caught or escaped, newest first:

- **Introduced by**: the PR that brought the bug in, with the `scrutiny::*`
  label it merged with, or "unknown" when no single PR did.
- **Touched**: what that PR changed in the area, in a few words.
- **Found by**: the first review, the second review, a stress run, the
  Self-check, a mutation sweep, a tier run, CI, a later issue's worker, an
  audit, the lead or a user.

| Found | Issue | Area | Introduced by | Touched | Found by | Escaped |
| --- | --- | --- | --- | --- | --- | --- |

## Bug log until 2026-10-09

Newest first, kept as it was under the area levels. "Escaped" means it was on
`main`, so it counts findings that were deferred after a review caught them,
and each bug is dated when it was found, not by the PR that introduced it.

| Date | Area | Bug | Found by | Escaped | Follow-up |
| --- | --- | --- | --- | --- | --- |
| 2026-10-07 | core: comparison | A kick reason is compared byte for byte, not as the text component the client shows (#335) | #333 review RD | yes | #335 open |
| 2026-10-07 | core: comparison | Divergences from windows a Candidate never played, after it failed an earlier window, are reported as gameplay (#334) | #333 review RD | yes | #334 open |
| 2026-10-07 | core: comparison | A network-traffic-only field (`batch_size` since #122, then `state_id`) adds a passing test case only when the sides differ, so a Candidate that differs scores higher (#330) | #329 reviews | yes | #330 open |
| 2026-10-07 | Groups | The fake `MovementServer` sent no `player_position`, so no unit test covered the clamped case's correction (#333 review RC S1) | review | no | fixed before merge |
| 2026-10-07 | tooling and docs | `mise run commit` fails with "failed to unpack tree object" on a shallow checkout (#326) | lead's first commit | yes | #326 open |
| 2026-10-04 | Groups | The `chat/limits` spam kick fell on a different message depending on where a tick landed, and `/tick freeze` cannot pin it because `TickThrottler` counts on every connection tick; a fake that kicked on the 3rd or 9th message passed every test (#269 review M1, S1) | review | no | fixed before merge (train 24) |
| 2026-10-04 | core: timing | Mutants of `Connection.send_all`'s failure paths (no closed check, no recording on cancel, no drain-error translation) survived (#269 review S2) | review | no | fixed before merge (train 24) |
| 2026-10-04 | core: timing | `observe` with a narrowed window left out one of several `until` names, so the Comparison could not see which ended it; an empty `until` gave a malformed `ProtocolError` (#271 reviews) | review | no | fixed before merge |
| 2026-10-04 | core: timing | A write that failed with more than 128 KiB buffered also dropped the last frames and the close (#292 review B1) | review | no | fixed before merge |
| 2026-10-04 | Groups | `chunks/*` took the join's first batch for the nearest chunks and ended a window when the view was held, so a Candidate that sends its whole view at once, or a ring one barrier later, was compared wrongly (#280 reviews B1, S2) | review | no | fixed before merge |
| 2026-10-04 | core: comparison | Pumpkin's join was sorted in three pieces: `set_health`, `set_experience` and `set_entity_data` between its chunk batches ended a run, so 18 chunks read as both left out and sent (#280 review B1) | review | no | fixed in #294, in the same train |
| 2026-10-04 | core: comparison | The latency broadcast (a `player_info_update`) came between two chunk batches on one Instance only and split the sorted runs differently: 32 chunks differed in `chunks/teleport`, play 15 of 20 under stress | Self-check of PR #280 | no | fixed in #294, in the same train |
| 2026-10-04 | core: comparison | A Group whose prerequisite was `error` was not `error` too, so an identical Candidate did not score full marks when vanilla failed the prerequisite (#289 review B, audit L2) | review | no | fixed before merge |
| 2026-10-04 | core: comparison | A Group blocked by an `error` prerequisite in one repetition failed the test cases it matched in the other repetitions (#289 review A B1) | review | no | fixed before merge |
| 2026-10-04 | core: comparison | A Group that failed and then lacked `kill` on its undo stack read `needs /kill`, which hid the Group's own failure (#288 reviews A L1, B L-288-1) | review | no | fixed before merge |
| 2026-10-04 | core: comparison | An unsettled Reference was played while the Candidate was frozen (#287 mutation batch) | mutation sweep | no | fixed in #287 before merge |
| 2026-10-04 | not yet known | A Reference block-events test required `block_update` where vanilla sent only `section_blocks_update`, once in a run (#303). A rerun on #305's branch passed | helper's reference tier on `main` | yes | random ticks turned covered grass to dirt in the same tick; fixed in #317 |
| 2026-10-04 | tooling and docs | `test_cli_candidate` still expected the run output from before #296 (#301) | train 22's candidate tier | yes | fixed in #304, in the same train |
| 2026-10-04 | not yet known | The 40-play `blocks/clone` Self-check: all 40 Verdicts were not `match`, with four `set_entity_data` packets (pose, health) missing from the Candidate's side, which was vanilla too (#300) | helper's Self-check on `main` | yes | Control joined at a saved spot under the clone's blocks; fixed in #322 |
| 2026-10-04 | tooling and docs | Concurrent test runs deleted each other's pytest temp directories: 323 errors on a good commit (#298) | train 22's checks | yes | fixed in #299 |
| 2026-10-04 | tooling and docs | A `test_live_lock` signal test failed once in `mise run check` and passed on the rerun (#295; #224 is the same file) | check run during the #28 rebase | yes | fixed in #327 |
| 2026-10-04 | core: comparison | `report_json`'s cap can drop the one Divergence that fans out, so `loads` gives other lines than the Report in memory: 4 passed, 1 failed, not 0 passed, 5 failed (#293). The file's own lines and totals are right | comparison-core audit of 2026-10-04 (L1) | yes | fixed in #316 |
| 2026-10-04 | core: timing | A Bot's read raised a raw `BrokenPipeError` after a kick, and the frames that arrived before the loss were dropped: `chat/limits` ended once in 400 stress plays (#291). #309 is its reset variant, once in a Pumpkin Run | Self-check of PR #269 | yes | fixed in #292; #309 open until a rerun confirms it |
| 2026-10-04 | core: timing | A Candidate without `/tick` is reported as having left its world frozen, so every later Group fails with the wrong reason (#290) | #288's worker, left for later | yes | fixed in #328 |
| 2026-10-04 | core: comparison | Failing a prerequisite scored better than passing it and failing its dependents (#285). No shipped Group has `requires`, so no Score was wrong yet | comparison-core audit of 2026-10-04 (M1) | yes | fixed in #289 |
| 2026-10-04 | core: comparison | A Candidate that lacked a command Control uses failed one line, not the Group's test cases, and a missing `/kill` on teardown threw away the Comparison (#284) | comparison-core audit of 2026-10-04 (H1) | yes | fixed in #288 |
| 2026-10-04 | Groups | A random tick turned the grass under the tick-exact probe's redstone block to dirt on one Instance only: a false `mismatch` in 1 of 20 plays (#272) | train 20's reference tier | yes | fixed in #275 |
| 2026-10-04 | tooling and docs | #268's stored Report sample went stale once #260 recaptured it | train 21's checks | no | re-rendered in #268 before merge |
| 2026-10-04 | core: comparison | #258's rule that a `bot` or `failed` Divergence is never network traffic broke #260's test, which built one | train 20's checks of each commit | no | fixed in #260 before merge |
| 2026-10-03 | core: comparison | A Candidate left unsettled fails each later Group as one line, not as its test cases, so it can score above one that sends every value wrong (#266) | review of PR #263, left for later | yes | fixed in #287 |
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
