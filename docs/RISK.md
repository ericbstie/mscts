# Risk register

Owned by the tech lead. It names the core areas the
[scrutiny nudge](PROCESS.md#lanes-and-review-levels) refers to, and logs every
bug found and every merged PR's review results, so the statistics can be
redone.

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
| 2026-10-22 | #462 | comparison core | #460 (`scrutiny::high`) | a recipe removed or put in another group passes when the book was replaced, or the recipe taken and given back, outside the windows first | the second review, the third review | no |
| 2026-10-22 | #457 | Groups | #457 (`scrutiny::high`) | `player/drowning` timed the turn-on of `drowning_damage` on the wall clock, so a vanilla server catching up got a round of bubbles without a hit | the first review | no |
| 2026-10-22 | #463 | Groups | unknown | the respawn window can catch `entity_event` 60 on one Instance only, in three player Groups | the first review of #457 | yes |
| 2026-10-22 | #461 | Groups | unknown | `join/basic` leaves the weather cycle on, so after about 20 minutes one Reference rains | a Self-check (#460's, run after the crafting Groups) | yes |
| 2026-10-22 | #456 | tests | unknown | the tick-exact reference test mismatched once in 20 plays under load, and its assertion hides the Divergence | a tier run (the reference tier of #452) | yes |
| 2026-10-22 | #455 | comparison core | #449 (`scrutiny::high`) | an element only vanilla has and one only the Candidate has can show at the same path | the third review | no |
| 2026-10-22 | #449 | comparison core | #449 (`scrutiny::high`) | lists indexed by slot or id (`container_set_content.slot_data`, `registry_data.entries`, `commands.nodes`) were lined up, so a moved item read as one left out | the first review, the second review | no |
| 2026-10-22 | #454 | tests | unknown | the `time/sleep` fake sent too few `set_time` in the lie-down window under load | a tier run (the unit tier under `rebase -x`) | yes |
| 2026-10-22 | #451 | comparison core | unknown | `registry_data` packets are paired by order, so registries in another order compare with each other | a worker (#256's Pumpkin measurement) | yes |
| 2026-10-22 | #450 | tests | #450 (`scrutiny::low`) | moving the Group test helpers lost the import that registers the shipped Groups, so a test file run alone found no Group | the lead's integration (each changed test file run alone) | no |
| 2026-10-22 | #445 | tests | #148 | a test that pins what one Pumpkin nightly sends failed when the nightly moved | a tier run (the candidate tier of #433) | yes |
| 2026-10-17 | #363 | comparison core | #433 (`scrutiny::high`) | a recipe book removal was compared in the order each server sent it | the first review, the second review | no |
| 2026-10-17 | #436 | Groups | unknown | a lava hit that came late under load landed in the dry-grass window, and `check_gap` (#367) did not catch it | the Self-check (#435's 20 plays) | yes |
| 2026-10-17 | #432 | tests | #415 (`scrutiny::high`) | the player fake's hit could beat the Bot's barrier under load, failing a unit test of the dry-grass window | a tier run (the unit tier under `rebase -x`) | yes |
| 2026-10-17 | #356 | timing core | #415 (`scrutiny::high`) | the early-packet refusal of a two-Bot `until` window depended on which Bot's reader stamped last | the first review | no |
| 2026-10-17 | #356 | tests | #415 (`scrutiny::high`) | the player fake hurt every tick after the lava teleport, so the dry-grass window lost its teleport under a 50 ms stall | the second review | no |
| 2026-10-16 | #411 | tooling | #414 (`scrutiny::low`) | a test's stand-in counted every stress process on the host, other workers' too | a tier run (the merge train's per-commit check) | no |
| 2026-10-16 | #418 | tooling | unknown | a live-lock waiter interrupted before it had the lock emptied the holder's pid file | a later issue's worker (#411) | yes |
| 2026-10-16 | #419 | tests | unknown | three tests accepted a TimeoutError from any step, #410's shape | the lead | yes |
| 2026-10-16 | #410 | tests | unknown | the repeater probe test accepted a TimeoutError from any step, so under load it timed out before its hang | a tier run (the unit tier under `rebase -x`) | yes |
| 2026-10-10 | #356 | timing core | unknown | a window's open Mark was stamped after Control's barrier, so a frame a Bot read with its own last answer fell before the Mark | a tier run (the unit tier) | yes |
| 2026-10-16 | #403 | tests | #379 (`scrutiny::high`) | a statistical Run's test told its sides apart by port, which two random hosts can share (1 in 14 000): the Reference was blamed | a tier run (the unit tier under `rebase -x`) | yes |
| 2026-10-16 | #63 | Groups | #400 (`scrutiny::high`) | the 50% sleep window compared only order: a skip at lie-down matched | the second review | no |
| 2026-10-16 | #63 | Groups | #400 (`scrutiny::high`) | the dawn window left out `system_chat`, hiding the wake-up message | the second review | no |
| 2026-10-16 | #63 | Groups | #400 (`scrutiny::high`) | a `set_time` that carries a clock never ended a wait: an invented failure | the second review | no |
| 2026-10-16 | #63 | Groups | #400 (`scrutiny::high`) | any `animate` ended the 50% sleep window | the first review | no |
| 2026-10-16 | #63 | Groups | #400 (`scrutiny::high`) | `spawn_mobs` turned on for every later play (a repeat of #344's) | a stress run | no |
| 2026-10-14 | #24 | comparison core | #379 (`scrutiny::high`) | every category rare pooled into one column, and the name was never tested | the re-review | no |
| 2026-10-14 | #24 | comparison core | #379 (`scrutiny::high`) | sample counts never compared: 500 samples against 2 matched | the second review | no |
| 2026-10-14 | #24 | comparison core | #379 (`scrutiny::high`) | a category only one side had was pooled into another and matched | the second review | no |
| 2026-10-14 | #24 | comparison core | #379 (`scrutiny::high`) | a statistical Group's plays were not independent: a Bot name rejoined at its saved place | the first review | no |
| 2026-10-09 | #330 | comparison core | unknown | the tick Divergence of a chunk batch marker | the first review of #341 | yes |
| 2026-10-09 | #342 | comparison core | unknown | the status `description` canonical form | the first review of #341 | yes |
| 2026-10-09 | #330 | comparison core | #341 (`scrutiny::high`) | a not-scored line ignored `NETWORK_TRAFFIC_ONLY_PASSES` | both reviews of #341 | no |
| 2026-10-09 | #36 | Groups | #343 (`scrutiny::medium`) | a survival dig's early finish rule; no early finish a Candidate could fail | the first review | no |
| 2026-10-09 | #56 | Groups | #344 (`scrutiny::medium`) | `spawn_mobs` turned on for every later Group | the first review | no |
| 2026-10-09 | #56 | Groups | #344 (`scrutiny::medium`) | a lava hit inside the fire hit's immunity, 1 play in 20 | the Self-check | no |
| 2026-10-09 | #53 | Groups | #346 (`scrutiny::medium`) | an extra world step while waiting for tracking | the first review | no |
| 2026-10-09 | #53 | Groups | #346 (`scrutiny::medium`) | sweep damage, knockback and sprint-hit health not compared | the first review | no |

## Review results

The lead adds one row per merged PR when it merges the train, newest first.
**Triage suggested** is the level the issue's triage comment suggested, left
empty when there was none. **Lead chose** is the `scrutiny::*` label the lead
set when it took the issue. **Reviews** lists the reviews that ran (the
lead's diff read, the first review, the second review). **Blocking findings**
gives the count each review found, in the same order. **Stress runs** gives how many ran and what they
caught, or "none".

| PR | Triage suggested | Lead chose | Reviews | Blocking findings | Stress runs |
| --- | --- | --- | --- | --- | --- |
| #501 |  | high | first review, second review; the lead's diff read of the fix round | 0, 1 (fixed: a dropper that never took the item out of its own slot passed, since no Bot held the dropper open) | none: no barrier or window change; Self-check 20 of 20 after the fixes; a stressed Self-check 20 of 20 in review A; mutation sweep 21 of 21 before the fixes; the 14 `redstone/*` Groups 3 of 3 and reference tier 36 of 36 on the train's tip |
| #500 |  | low | the lead's diff read | 0 | none: test helpers only; six reference tests once from a detached copy |
| #499 |  | low | the lead's diff read | 0 | none: tooling; 62 unit tests of `repeat.py`; mutation sweep 28 of 28; each new flag used live once |
| #498 |  | low | the lead's diff read | 0 | none: the Adapter's config; candidate tier 15 of 15 (14 of 15 on main); mutation sweep 6 of 6 |
| #494 |  | high | first review, second review; the lead's diff read of the fix round | 0, 2 (both fixed: `hopper-full` and `hopper-lock` let a hopper that retries every 2, 3 or 6 ticks pass; no hopper pushed while holding two stacks) | none: no barrier or window change; Self-check 20 of 20 of each of the four Groups after the fixes; mutation sweep 32 of 32 before the fixes; the nine other `redstone/*` Groups 3 of 3 after the helper rename; reference tier 36 of 36 on the restacked head |
| #492 |  | medium | the lead's diff read | 0 | 5 of 5, each 20 of 20, of `player/void`; Self-check 20 of 20 of `player/void`, `player/drowning`, `player/fall`; mutation sweep 4 of 4; the respawn request leaves 298 ms (median) after the death, against event 60's 1000 ms |
| #491 |  | medium | the lead's diff read | 0 | none: a check before the respawn, no step moved (waived as for #463); Self-check 20 of 20 of `combat/death` twice; mutation sweep 7 of 7 |
| #486 | low | low | none | 0 | none: a span only; Self-check of `player/drowning` 3 of 3 on the train tip; reference tier 36 of 36 |
| #485 | medium | high | first review, second review, third review of the fixes; the lead's diff read of the third fix round | 0, 0, 0 (should-fix: the first fix took the step out of the lethal fall window, so a Candidate killing 200 ms late became a mismatch; fixed in round 3 by ending the window on the death) | 5 of 5, each 20 of 20, of `player/fall` after round 3; mutation sweeps 6 of 6 and 8 of 8, then 10 of 10; review C's late-death probe matches from +50 ms to +3000 ms |
| #484 | low | low | none | 0 | none: tooling; `player/fire` played live once, each of its four windows has a compared packet |
| #483 | low | low | none | 0 | none: titles and docs only; a 5-play Pumpkin run of `redstone/*`: all 28 `block_event` test cases are in `TITLES`; no mutation sweep (table entries and prose) |
| #482 | low | low | none | 0 | none: a recorded table in a Candidate test; the candidate tier 15 of 15 on the train's tip, with the new table (the test failed on the old one); no mutation sweep (an exact-equality pin) |
| #476 | high | high | first review, second review, third review of the fixes; the lead's diff read of the second fix round | 0, 0, 0 (should-fix: a recipe first seen outside the windows stayed a name for good, a false mismatch; fixed in round 2) | none: no barrier or window change; Self-check 20 of 20 of the three crafting Groups and `join/basic` after round 2; mutation sweep 33 of 39 killed (killers added for four, five explained), then 8 of 8 after the killers; review C's probes and 4-mode fuzz, 0 wrong |
| #475 | high | high | first review, second review, third review of the fixes | 0, 0, 0 (should-fix: b's fixed, c's filed as #477; the lead narrowed the docs) | none: no barrier or window change; mutation sweep 7 of 7 killed, then 11 of 12 (the 12th killed by the new pins) and a narrower sweep with one survivor |
| #474 | high | high | first review, second review, third review of the fixes | 0, 0, 0 (should-fix 1, 1, both fixed) | none: no barrier or window change; mutation sweep 28 of 33 killed (5 equivalent); the lead accepted that the place of a neutral packet is dropped (C4) |
| #468 | low | low | lead's diff read | 0 | none: a failure message; the probe Self-check 35 of 35 under `--stress` (no failure to read); mutation sweep 11 of 11 killed |
| #467 | medium | medium | lead's diff read | 0 | five stressed 20-play Self-checks of `join/basic`, 5 of 5; Self-check 20 of 20 of `join/basic` after the three crafting Groups; mutation sweep 6 of 6 killed |
| #466 | medium | medium | lead's diff read | 0 | five stressed 20-play Self-checks of `time/sleep`, 5 of 5; the unit tests 35 of 35 under `--stress`; 3 of 176 probe plays short on main under `-n 8 --stress`, 0 of 240 after; mutation sweep 3 of 3 killed |
| #458 |  | high | first review, second review | 0, 0 | none: no barrier or window change; Self-check 20 of 20 of the three piston Groups and once of the six other redstone Groups; mutation sweep 38 of 38 killed |
| #457 | high | high | first review, second review, third review of the fixes | 1 (the turn-on of `drowning_damage` timed on the clock), 0, 0 | five stressed 20-play Self-checks of `player/drowning`, 5 of 5; Self-check 20 of 20 after the fixes; mutation sweep 16 of 16, then 10 of 10 |
| #460 |  | high | first review, second review, third review of the fixes | 0, 0, 0 (should-fix findings fixed or filed as #462) | none: no barrier or window change; Self-check 20 of 20 of the three crafting Groups and `join/basic`; mutation sweep 20 of 20, then 10 of 11 (one equivalent) |
| #459 | high (low if only the limit is named) | low | lead's diff read | 0 | none: docs only |
| #449 |  | high | first review, second review, third review of the fixes | 1, 1 (the same: lists indexed by slot or id lined up), 0 (should-fix filed as #455) | none: no barrier or window change; the Self-check tier 81 of 81; mutation sweep 49 of 49 killed |
| #452 |  | medium | lead's diff read | 0 | none; Self-check 20 of 20 of the three status Groups; mutation sweep 16 of 16 killed |
| #453 |  | medium | lead's diff read | 0 | none; live installs of vanilla and Pumpkin into scratch caches; mutation sweep 35 of 35, then 3 of 3 |
| #448 |  | medium | lead's diff read | 0 | none; Self-check 20 of 20 of `crafting/grid`; mutation sweep, 44 killed |
| #444 |  | high | lead's diff read | 0 | five stressed 20-play Self-checks of `player/fire`, 5 of 5; `player/fall` 20 of 20; #432 under load 35 of 35 against 31 of 35 on main; mutation sweep 16 of 17 (one unreachable) |
| #450 |  | low | lead's diff read | 0 | none; every changed test file run alone (81 of 84 pass; the other 3 need Java 25 and passed in the reference tier) |
| #440 |  | medium | lead's diff read | 0 | none: no barrier or window change; Self-check 20 of 20 of the six redstone Groups; mutation sweep 78 of 80 |
| #433 |  | high | first review, second review, third review of the fixes | 1, 1 (the same: removal order compared), 0 (2 should-fix, filed as #443) | none: no barrier or window change; Self-check 20 of 20 of the four Groups; mutation sweep 20 of 20 killed |
| #439 |  | medium | lead's diff read | 0 | five stressed 20-play Self-checks of `player/exhaustion`, 5 of 5 (it changes how many ticks pass between jumps); Self-check 20 of 20; mutation sweep 11 of 11 killed |
| #437 | high | medium (one send, no wait) | lead's diff read | 0 | none: no barrier or window change; Self-check 20 of 20 of `inventory/offhand`; mutation sweep 26 of 26 killed |
| #435 | medium | medium | lead's diff read | 0 | none: no barrier change; Self-check 20 plays of the nine player Groups, 8 of them 20 of 20 and `player/fire` 19 of 20 (an older guard bug, #436); mutation sweep 16 of 16 killed |
| #434 | high | low (a probe only) | lead's diff read | 0 | none: a probe; in order 100 of 100 on both servers, idle and under `--stress 4` |
| #431 | high | low (only the message changes) | lead's diff read | 0 | none: the rebase's per-commit check caught the #432 flake once |
| #430 | medium | low (test only) | lead's diff read | 0 | none: `player/starvation` 20 of 20 at 103 s a play |
| #429 | low | low | lead's diff read | 0 | none: a research script |
| #415 | high | high | first review, second review | 0, 0 (3 should-fix, all fixed) | five stressed 20-play Self-checks of `player/drowning` before the reviews, 5 of 5; the first 50-run unit stress caught the player fake hurting after `fresh`, fixed; after the fixes one stressed 20-play Self-check each of `player/fire` and `player/drowning`, 20 of 20, and the unit tests 50 of 50; Self-check tier 74 of 74 on the tip; mutation sweep 11 of 11 killed |
| #422 | high | medium | lead's diff read | 0 | none: no barrier or window change (the lead lowered it: the schema's fields are a position and a VarInt, so equal bytes and equal fields agree); Self-check 20 of 20 of `blocks/gravity`; mutation sweep 16 of 16 killed |
| #421 | low | low | lead's diff read | 0 | none: tests only; the three tests 50 of 50 under `repeat.py --stress` |
| #420 | low | low | lead's diff read | 0 | none: tooling; 50 of 50 under `repeat.py --stress`; mutation sweep 7 of 7 killed |
| #417 | low | low | lead's diff read | 0 | none: tooling; mutation sweep 31 of 31 killed |
| #414 | | low | lead's diff read | 0 | none: tooling; mutation sweep 20 of 20 killed; the merge train's per-commit check caught one red commit |
| #416 | low | low | lead's diff read | 0 | none: test only; the test 100 of 100 under `repeat.py --stress` |
| #409 | medium | medium | lead's diff read | 0 | five statistical Self-checks of `mobs/*`, 5 of 5; mutation sweep 15 of 16 killed, the 16th timed out and was killed alone |
| #408 | medium | medium | lead's diff read | 0 | none: no barrier or window timing change; Self-check 20 of 20 of `blocks/fill` and `inventory/give`; mutation sweep 8 of 9 killed, a pin test kills the 9th |
| #407 | low | low | lead's diff read | 0 | none: research note and probe, no product code |
| #406 | high | low | lead's diff read | 0 | none: test only (the lead lowered it once the cause was in the test); the test 5 of 5 under `repeat.py --stress` |
| #400 | | high | first review, second review | 0, 0 (3 high, all fixed) | five Self-checks of `time/*` before the reviews: run 1 failed on a `spawn_mobs` undo, fixed; five after the fixes, 20 of 20 each |
| #398 | medium | medium | lead's diff read | 0 | five statistical Self-checks of `mobs/*`, 5 of 5 |
| #401 | | medium | lead's diff read | 0 | none: no barrier or window change; Self-check 20 of 20 of six `combat/*` Groups |
| #397 | low | low | lead's diff read | 0 | none: tooling |
| #394 | medium | medium | lead's diff read | 0 | none: research note and probe, no product code |
| #391 | | high | first review, second review, re-review | 1, 1 (the same: an uncompared packet ended a run of resends), 1 (runs crossed a window boundary) | five Self-checks of `blocks`, `entities`, `combat` before the reviews and five after the first fix, 26 of 26 each; one after the window fix, 27 of 27; none caught a bug |
| #393 | | medium | lead's diff read | 0 | none: no barrier or window change; statistical tier 7 of 7 on the train tip |
| #390 | medium | medium | lead's diff read | 1: the replay played on the shared pair, so `spawn/*` re-sampled the first play's positions | none: no barrier or window change; the lead forced the replay live once, 1 of 1 |
| #392 | | medium | lead's diff read | 0 | five Self-checks of `combat/pvp-off`, 20 of 20 each; no mutation sweep |
| #386 |  | medium | lead's diff read | 0 | none: no barrier or window change; each Group's statistical Self-check passed |
| #385 |  | medium | lead's diff read | 0 | none: no barrier or window change; statistical Self-check passed for both Groups |
| #379 |  | high | lead's diff read, first review, second review, re-review | 0, 1, 2, 1 | none: no barrier or window change |
| #381 | medium | medium | lead's diff read | 0 | 5, all green: `blocks/dig-survival` 100 of 100 plays |
| #380 | medium | medium | lead's diff read | 0 | none: no barrier or window change; Self-check 20 of 20 for each touched Group |
| #378 | low | low | lead's diff read | 0 | none |
| #367 | high | high | lead's diff read, first review, second review | 0, 0, 0 | 5 per family, all green: inventory 100 of 100 plays, movement 200 of 200, blocks 300 of 300, combat 600 of 600, `player/fall` 100 of 100 (its first series was killed by the lead and rerun from the start); the full 3-request barrier of the first branch had overrun `player/fall`'s budget |
| #372 |  | high, lowered to medium (no core change) | lead's diff read | 0 | none: no barrier or window change; the worker found a scheduled fluid tick saved with the chunk and run in the next play (1 of 2 plays), fixed before the PR |
| #371 |  | high, lowered to medium (no core change) | lead's diff read | 0 | none: no barrier or window change; the worker's Self-check matched 18 of 20 while it compared falling-block movement, which it then left out |
| #366 |  | medium | lead's diff read | 0 | none: no barrier or window change; the lead dropped a duplicate titles commit that #365 already carried |
| #365 |  | high, lowered to medium (no comparison-core change) | lead's diff read | 0 | none: no barrier or window change; the worker's Self-check found bodies outliving `remove_tagged` (3 of 20 plays), fixed before the PR |
| #361 |  | medium | first review | 0 | none: no barrier or window change; the Self-check after the review fixes found the crafting table's undo leaving dirt where grass was on one Instance, fixed before the merge |
| #358 |  | medium | first review | 0 | none: no barrier or window change |
| #357 | low | low | lead's diff read | 0 | none: test code only |
| #352 |  | medium | first review | 0 | none: no barrier or window change; the Self-check after the review fixes found the husk cleanup unloading its own chunk, 4 of 5 plays, fixed before the merge |
| #351 |  | medium | first review | 0 | none: no barrier or window change |
| #353 |  | medium | first review | 0 | none: no barrier or window change |
| #348 |  | none | lead's diff read | 0 | none |
| #346 |  | medium | first review | 2 | none: tick-exact Groups, the review judged the wall-time gaps wide enough |
| #344 |  | medium | first review | 1 | 5 runs of 20 plays after the fix, 0 failing; the Self-check found a lava hit inside the fire hit's immunity, 1 in 20 |
| #343 |  | medium | first review | 2 | 2 of 5 runs of `blocks/dig-survival` before it moved to #347, both clean |
| #341 |  | high | first review, second review | 0, 0 | none: no timing |
| #339 |  | none | lead's diff read | 0 | none |
| #340 |  | low | lead's diff read | 0 | none |

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
