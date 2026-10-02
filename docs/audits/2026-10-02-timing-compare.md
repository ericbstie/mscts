# Audit AT: timing and comparison (what every Verdict rests on)

Date: 2026-10-02. Base: `main` at `fc7dce2`. Auditor: an opus auditor, read-only.

Scope, the code that has landed since the 2026-09-26 audits without one:

- **Timing**: `src/mscts/net.py` (arrival stamps, the frames of one read),
  `src/mscts/bot.py` (`Bot.sync`, the barrier with its gap check, and `join`),
  `src/mscts/settle.py` (`until_no_player_online`), `src/mscts/group.py`
  (Observation windows, `observe(until=...)`, Control, `Control.leave` and the
  rejoin, the `tellraw` marker) and `src/mscts/transcript.py`.
- **Comparison**: `src/mscts/compare.py` (the `UNORDERED` sorts,
  `RANDOM_FIELDS`, Masks and the refusal of a Mask on an entity id, per-Bot
  entity numbering with `src/mscts/codec/entity_ids.py`, gameplay and network
  traffic kinds, test-case naming) and `src/mscts/run.py` (Self-check,
  Verdicts, `error` and `mismatch` for Candidate-caused failures).

Method: read every module in scope and its tests against `CONTEXT.md`,
`docs/PLAN.md`, ADR-0006, ADR-0007, ADR-0010 (with its three amendments) and
ADR-0011, and the PROCESS audit checklist. Each finding below that says
"probe" rests on a throwaway script run against the repo's own fakes
(`tests/net/fakes.py`, `tests/compare/build.py`) and quotes its output. The
scripts are in the session scratchpad (`probe_*.py`); none is committed.
`mise run check` was green at the base (2,934 passed, 2 skipped, 12.3 s).
A narrow mutation sweep (48 mutants, 42 killed) ran through
`scripts/mutate.py --batch`. The reference tier and `test:selfcheck` were not
run: nothing in this audit needs a live Instance, and other agents share the
machine.

Severity follows the foundation audit: **critical** = wrong Verdicts in
current use; **high** = wrong Verdicts (or a lost Run) as soon as the Groups
now being written use the code, with no test failing; **medium** = a contract
or tooling defect with a plausible path to a wrong result; **low** = hygiene,
docs, edge cases. Each finding is tagged with its domain: *timing* or
*comparison*.

## Executive summary

The window machinery is careful where it has been measured: the arrival
stamps, the nanosecond spacing of one read's frames, the Mark-time tie rule
(a packet stamped at a Mark's time is after it) and the `until` close Mark
agree with each other, and Compare survives the deepest value the codec can
decode. The Verdict rule (`judge`) is right for every exception the brief
lists. No finding is critical: only the two status Groups ship today.

But five defects will corrupt Verdicts, or lose a whole Run, as soon as the
gameplay Groups (#30 and after) use these modules, and no current test would
notice:

1. **H1 (timing). The barrier's tick gap is measured on the harness's own
   clock, so a stall in the harness invents a tick.** The stamp of an answer
   is when the event loop read it, not when it reached the socket. A 12 ms
   stall right after the pair's second request made `Bot.sync` return after
   one pair, against a fake that answered both requests in one pass
   ("pair gaps ms=[12.33]", no `sync:capped` Mark). An idle loop on this
   machine woke 5 ms or more late 8 times in 17,080 (max 44.6 ms), at load
   0.3. Under the load that #88 measured, that is the 2-in-529 failure back,
   with no Mark to show it.
2. **H2 (comparison). Entity numbering hides an action on the wrong entity
   when the entity was spawned before the window.** Since #108, only compared
   packets take numbers, so the first entity a window names is `#1` whichever
   entity it is. A Candidate that hurts the cow where vanilla hurts the pig
   (both spawned in setup) gets `match`.
3. **H3 (comparison). A Candidate's status JSON can crash the whole Run, or
   make a Group `error`.** `Bot.status` catches only `JSONDecodeError`, so
   JSON that `json.loads` refuses with a `ValueError` (an integer of more than
   4,300 digits) or a `RecursionError` (16,000 nested brackets) escapes. In
   `status/basic` it is `error`, which the compliance score leaves out; in the
   settle wait that `run_results` makes before **every** Group, it propagates
   out of `asyncio.gather` and ends the Run with no Verdicts at all.
4. **H4 (comparison). `PlayersStillOnline` raised inside a Group is `error`,
   not `mismatch`.** The guide and ADR-0010 (#105) tell a Group to wait with
   `until_no_player_online` after `control.leave()`. A Candidate that never
   drops the player then gets `error` ("the harness failed on the
   Candidate"), against audit H3's rule.
5. **H5 (timing). A stray `award_stats` turns the barrier into one round
   trip.** `_ask_for_statistics` takes the next `award_stats` whoever asked
   for it. One the Bot did not ask for (a Candidate that answers twice, or
   sends one unasked) is taken as the first answer, the real one as the
   second, and their gap passes. Probe: the tick's `block_update` came after
   `sync` returned. The offset persists for every later barrier on that Bot,
   and `award_stats` is a heartbeat packet, so the cause is never compared.

Among the rest: a window narrowed to a misspelt or heartbeat packet name
compares nothing and matches (MD1); the close Mark of a barrier window is the
same for every Bot and is stamped when the slowest Bot's barrier returns, so
the faster Bots' windows take in timing-dependent packets (MD2); a Candidate
that reuses an entity id after removing the entity gets a cascade of invented
gameplay Divergences (MD3); and four mutants survive for want of a test,
among them the 5 ms threshold itself (MD4). Every window, `until`, Control,
numbering, heartbeat and Verdict-rule branch mutated was killed.

## Findings

Mutation ids (N, B, G, S, C, E, R) are in the [mutation log](#mutation-log).

No critical findings: the only shipped Groups are `status/basic` and
`status/ping`, which have no window, no Control and no entity.

### H1 (high, timing). A stall in the harness invents the barrier's tick

- **Location**: `src/mscts/bot.py:386-401` (the pair and the gap check at
  `:391`), `:403-408` (`_ask_for_statistics` returns
  `Connection.last_arrival_ns`); the stamp is taken at
  `src/mscts/net.py:287-288`, after `StreamReader.read` returns.
- **Evidence**: `probe_stall.py` runs `play_server(answer_at_once)` (both
  answers of a pair in one "pass", 0.3 ms apart) in a thread of its own, so
  that the fake keeps answering while the Bot's loop is blocked, and blocks the
  Bot's loop for 12 ms right after each pair's second request:

  ```
  stall=False: requests=6 marks=['sync:capped alice'] pair gaps ms=[0.34, 0.34, 0.34]
  stall=True: requests=2 marks=[] pair gaps ms=[12.33]
  ```

  How often the loop stalls that long on this machine, at load 0.3, idle
  (`probe_loop_lag.py`, 20 s of `asyncio.sleep(0.001)`):

  ```
  load 0.3: 17080 wakes, median lag 0.13 ms, p99.9 2.97 ms, max 44.60 ms, 8 wakes 5 ms or more late
  ```

  The arrival stamp (#88, foundation H2) is the time the background reader's
  `read()` returned. That is the arrival only while the loop is free. If the
  process is descheduled, collects garbage, or another task (another Bot's
  reader decoding a chunk burst, in a multi-Bot barrier) holds the loop after
  the second request is sent, the second answer is stamped late by that much,
  and the pair "shows a tick" that the server never made. The existing test
  `test_the_gap_is_between_when_answers_arrived_not_when_the_bot_took_them`
  delays the Bot with `asyncio.sleep`, which leaves the reader free to stamp,
  so it cannot see this.
- **Failure scenario**: the #88 failure, back. Vanilla answers both requests
  in one pass (12 of 600 sides had a pair closer than 5 ms); the harness is
  descheduled for 6 ms after the second request; `sync` returns after one
  pair, before the tick that sends the `block_update`; the window closes
  without it on one side. Self-check fails 1 time in a few hundred under load,
  or a Candidate gets a `missing` Divergence it did not cause. No
  `sync:capped` Mark is left, so the Transcript does not show it.
- **Fix, test first** (`tests/net/test_bot_sync.py`): *"a Bot whose loop
  stalls after a pair's second request does not take a one-pass pair for a
  tick"*: a vanilla-like fake served from its own thread (so it keeps time
  while the Bot's loop is blocked, as `probe_stall.py` does): a request opens
  a 3 ms pass that answers every request arriving in it, the tick's
  `block_update` follows 30 ms after the pass, and the next pass a tick later;
  the Bot's loop is blocked 12 ms (`time.sleep`) after the pair's second
  request. Expect the `block_update` to be taken before `sync` returns. Today
  it is not. Then change the proof from "the answers arrived `TICK_GAP_S`
  apart" to "the second request was **sent** at least `TICK_GAP_S` after the
  first answer arrived" (compare the sent Event's `t_ns` with the answer's
  arrival). A stall can only lengthen that interval in real time, and it rests
  on the same server fact as the amendment (a pass lasts under 5 ms), so it is
  one-sided: it never takes a one-pass pair for a tick. It also needs no
  retries (one pair, a 5 ms wait, always), so the cap goes; keep the measured
  gap as a diagnostic Mark (e.g. `sync:one-pass <Bot>` when the answers came
  under 5 ms apart anyway) so a server with no ticks still shows. This contradicts
  ADR-0010's 2026-10-02 amendment item 2 ("Between the two requests of a pair
  it would put the answers TICK_GAP_S apart whatever the server does, and the
  gap would prove nothing"): that is true of the gap as proof, not of the
  wait as proof. It needs a decision comment, and the brief-template rule for
  a barrier change (20 of 20 Self-checks, five times in a row, under
  `repeat.py --stress`).

### H2 (high, comparison). Numbering hides an action on the wrong entity spawned before the window

- **Location**: `src/mscts/compare.py:503-523` (`_stream` numbers only
  `taken`), `:655-688` (`_Numbers.of`); the decision is #108 (PROCESS
  retrospective 2026-10-02, worker AQ).
- **Evidence** (`probe_entity_hidden.py`): both sides spawn a pig (id 5) and a
  cow (id 6) before the window; inside it, the Reference sends
  `hurt_animation(5)` and the Candidate `hurt_animation(6)`:

  ```
  hurt the wrong pre-window entity: match
  ```

  Each side's first id in the window becomes `#1`, so the pig and the cow
  compare equal. `test_inside_a_window_the_first_entity_it_names_is_number_one`
  asserts exactly this numbering, so the tests pin the hiding.
- **Failure scenario**: the test-group routine sets the world up before the
  window and acts inside it. Any Group that spawns two entities in setup
  (`/summon`) and tests what happens to one of them (damage, a leash, a name
  tag, an interaction) cannot tell which entity the Candidate changed. A
  Candidate that applies the effect to the wrong mob gets `match`.
- **Fix, test first** (`tests/compare/test_entity_ids.py`): *"an action
  inside a window on another entity spawned before it is a Divergence"* (the
  probe above, expecting `mismatch` at `hurt_animation.entity_id`). Then give
  an id whose `add_entity` is outside the windows a name from that
  `add_entity`, not from timing: its entity type and spawn position, e.g.
  `pig@(1.5, -60.0, 7.5)`. Those are fixed by the Group's own setup, and
  unaffected by how many natural or world-gen entities arrived before (the
  #108 problem). Ids with no `add_entity` in the Transcript keep the
  first-appearance number. Keep `#n` for entities spawned inside a window.
  Same-type entities at one position are still ambiguous; the test-group
  skill should say so.

### H3 (high, comparison). Candidate status JSON can end the Run, or make a Group `error`

- **Location**: `src/mscts/bot.py:542-555` (`_json_object` catches only
  `json.JSONDecodeError`), reached from `Bot.status` (`:260-274`), from
  `settle._players_online` (`src/mscts/settle.py:116`, whose `_UNREADABLE` at
  `:40` lacks `ValueError` and `RecursionError`), and from `status_probe`;
  `src/mscts/run.py:557` (`asyncio.gather` in `_unsettled`).
- **Evidence** (`probe_deep_json.py`, `probe_settle.py`, fake status servers):

  ```
  nested 100: mismatch cause=ProtocolError detail='the Candidate failed: ProtocolError: status_response json_response is not a JSON object'
  nested 16000: error cause=RecursionError detail='the harness failed on the Candidate: RecursionError: maximum recursion depth exceeded while decoding'
  5000-digit int: error cause=ValueError detail='the harness failed on the Candidate: ValueError: Exceeds the limit (4300 digits) for integer string '
  5000-digit int: settle raised ValueError: Exceeds the limit (4300 digits) for integer string conversion: value h
  5000-digit int: _unsettled (run_results) raised ValueError
  nested 16000: _unsettled (run_results) raised RecursionError
  ```

  Both payloads fit the 32,767-character status string. `compare._strict_json`
  and `run.status_version` already catch both errors; `Bot.status` does not.
- **Failure scenario**: a Candidate whose status JSON holds a huge number (a
  plugin's counter, a corrupt `players.online`) or deep nesting. Every Group's
  settle wait raises before the Group is played, `run_results` unwinds, and
  the user gets a traceback instead of a Report. If the Run gets past the
  settle (the Reference raised first), `status/basic` is `error` and leaves the
  compliance score. `gather` does not cancel the other side's poll either, so
  that task runs on, unawaited, while the Run stops its Instances.
- **Fix, test first**: (a) `tests/net/test_bot.py`: *"a status whose JSON
  `json.loads` refuses with ValueError or RecursionError raises ProtocolError"*;
  `_json_object` catches `(ValueError, RecursionError)` (JSONDecodeError is a
  ValueError). That covers `status`, settle and `status_probe` at once.
  (b) `tests/run/test_run_settle.py`: *"a Candidate whose settle poll raises
  something unexpected gets a `mismatch`, and the Run goes on"*: `_left`
  turns anything but `PlayersStillOnline` from a poll into a `failed`
  Divergence, never a crash. (c) An audit-checklist item: "every `json.loads`
  of server text catches ValueError and RecursionError".

### H4 (high, comparison). `PlayersStillOnline` inside a Group is `error`, not `mismatch`

- **Location**: `src/mscts/run.py:35-40` (`CANDIDATE_FAILURES`) and
  `:245-248` (`judge`); the advice is in `src/mscts/group.py:70` and `:161`,
  `docs/guide/writing-a-group.md:64` and ADR-0010 (#105) item 3.
- **Evidence** (`probe_judge.py`, `judge` on a Candidate `GroupError` caused
  by `PlayersStillOnline(1, ["control"], 2.0)`):

  ```
  error | the harness failed on the Candidate: PlayersStillOnline: ...
  ```

  `PlayersStillOnline` is a plain `Exception`, not in `CANDIDATE_FAILURES`.
  Between Groups, `_unsettled` maps it to `mismatch` by hand
  (`run.py:563-569`); inside a Group nothing does.
- **Failure scenario**: #30's join Group sets its Fixture, calls
  `control.leave()`, then `until_no_player_online` before its Bot joins, as the
  guide says. A Candidate that keeps a closed Bot's player listed for over 2 s
  makes that Group `error`, which the score leaves out: the Candidate scores
  higher than one that drops the player late but within 2 s and then differs.
- **Fix, test first** (`tests/run/test_verdict_rule.py`): *"a Group that
  raises PlayersStillOnline on the Candidate is a mismatch led by a failed
  Divergence, and an error on the Reference"*. Add `PlayersStillOnline` to
  `CANDIDATE_FAILURES` (and to PLAN's line 1148). Also name it in the brief
  rule "state each new failure path's Verdict" as the example it was meant to
  catch.

### H5 (high, timing). A stray `award_stats` makes the barrier one round trip

- **Location**: `src/mscts/bot.py:403-408` (`_ask_for_statistics` takes the
  next `award_stats`, whenever it arrived), with `:388-392`.
- **Evidence** (`probe_stale_stats.py`): the fake answers like vanilla (the
  first request of a pair at once, the tick body's `block_update` 30 ms later,
  the second request at the next tick, 50 ms later). With one unasked
  `award_stats` sent before the barrier:

  ```
  stray award_stats=False: before sync returned: ['client_command', 'award_stats', 'client_command', 'block_update', 'award_stats']
  stray award_stats=True: before sync returned: ['award_stats', 'client_command', 'client_command', 'award_stats']
  ```

  The first request takes the stray answer (arrived long before), the second
  takes the first request's answer, and their gap passes. The barrier returned
  before the tick's `block_update`. Its own second answer is still queued, so
  every later barrier on that Bot is offset the same way.
- **Failure scenario**: a Candidate that answers `REQUEST_STATS` twice, or
  sends `award_stats` on its own (an achievement or statistics plugin). Every
  window then closes after one round trip, so its late effects fall outside
  and show as `missing`, a `mismatch` for a reason no Divergence names:
  `award_stats` is a heartbeat packet, never compared in a window.
- **Fix, test first** (`tests/net/test_bot_sync.py`): *"an award_stats that
  arrived before the request is not its answer"* (the probe's fake, expecting
  the `block_update` before `sync` returns). Then let `_ask_for_statistics`
  skip any `award_stats` whose arrival is before its own request's send stamp.
  With H1's fix (the wait as proof) this is the only matching rule needed.

### MD1 (medium, comparison). A window narrowed to a wrong name compares nothing, and matches

- **Location**: `src/mscts/group.py:311-314` (a name is checked only for being
  one word); `src/mscts/compare.py:580`.
- **Evidence** (`probe_narrow.py`, a different `block_update` on each side):

  ```
  observe('minecraft:block_updat') accepted: True
    a different block_update in a window narrowed to 'minecraft:block_updat': match, test cases ()
  observe('minecraft:set_time') accepted: True
    a different block_update in a window narrowed to 'minecraft:set_time': match, test cases ()
  observe('block_update') accepted: True
    a different block_update in a window narrowed to 'block_update': match, test cases ()
  ```

- **Failure scenario**: a typo, a name without its namespace, or a heartbeat
  name in a Group's `observe(...)`. The Group passes its Self-check (both sides
  compare nothing) and matches every Candidate.
- **Fix, test first** (`tests/group/test_observe.py`): *"observe refuses a
  name that is not a clientbound play packet of the Target, or is a heartbeat
  packet"* (ValueError, nothing marked), and the same for `until`. Check
  against `Codec.names(State.PLAY, Direction.CLIENTBOUND)`. Optionally, a
  `match` that compared no test case at all could be flagged by `run`.

### MD2 (medium, timing). One close Mark for every Bot, stamped when the slowest barrier returns

- **Location**: `src/mscts/group.py:319-322` and `:373-381`.
- **Evidence**: by reading. `_sync` runs every Bot's barrier at once, and the
  close Mark is taken with `now_ns()` after the last one returns. A Bot whose
  barrier ended in one pair keeps taking packets into its window while
  another Bot does up to two more pairs, each after a 5 ms wait (up to about
  three ticks), and every Bot keeps taking them for as long as the loop takes
  to get from its last answer to the Mark. What arrives then (vanilla's
  `move_entity_pos` resend every 60 ticks, `player_info_update` every 601, mobs
  walking into view) depends on the timing, not on the Group. ADR-0010 item 3
  asks a Group to narrow its window when it can catch one; nothing says the
  window's end depends on the other Bots.
- **Failure scenario**: a two-Bot Group whose window is not narrowed: one Bot
  caps, the other takes a `move_entity_pos` that arrived during the extra
  pairs. Self-check fails now and then, under load more often.
- **Fix, test first** (`tests/group/test_observe.py`): *"each Bot's window
  ends at its own barrier's last answer"*: a two-Bot fake where one Bot's
  barrier takes two pairs and the other gets a straggler meanwhile; expect
  the straggler outside. Record the close per Bot (`observe:close <bot>`,
  stamped at that Bot's last answer's arrival plus 1 ns) and have
  `_Windows.of` read a Bot's own close Mark. This needs an ADR-0010
  amendment.

### MD3 (medium, comparison). An entity id reused after its removal invents a cascade of Divergences

- **Location**: `src/mscts/compare.py:655-688` (`_Numbers.of` keys by id over
  the whole stream).
- **Evidence** (`probe_entity_hidden.py`): the same spawns, removals and hurts
  on both sides, but the Candidate gives the second pig the id it freed:

  ```
  id reused after removal: mismatch
     2 minecraft:add_entity entity_id #2 #1 add_entity.entity_id
     3 minecraft:hurt_animation entity_id #2 #1 hurt_animation.entity_id
     4 minecraft:add_entity entity_id #3 #2 add_entity.entity_id
     5 minecraft:hurt_animation entity_id #3 #2 hurt_animation.entity_id
  ```

  The vanilla client handles a reused id as a new entity (`remove_entities`
  then `add_entity`), so a player sees no difference; every later entity's
  number shifts, and every test case that names an entity id differs.
- **Fix, test first**: *"an id reused after remove_entities is a new entity"*
  (the probe, expecting `match`). End an id's number at `remove_entities`. It
  matters only if a Candidate reuses ids (vanilla never does), hence medium.

### MD4 (medium, both). Four mutants of the riskiest branches survive for want of a test

Of 48 mutants, 42 were killed and 6 survived; two are equivalent (B1, G13,
see the [mutation log](#mutation-log)). The other four each need a test:

- **B2 (timing)**, `src/mscts/bot.py:391`: halving the gap threshold
  (`TICK_GAP_S * 1e9 // 2`) survives. Every sync test widens the gap to
  100 ms (`wide_gap`), so nothing pins the 5 ms value against the measured
  3.6 ms widest one-pass pair. Test: *"with the real `TICK_GAP_S`, two answers
  3.6 ms apart are one pass, and 5.4 ms apart are a tick"* (a fake that answers
  the pair's second request after a set delay). This is the number the whole
  #88 amendment rests on. (Moot if H1's fix replaces the gap.)
- **S2 (timing)**, `src/mscts/settle.py:93`: a deadline one second late
  survives. Test: *"PlayersStillOnline comes within `deadline_s` plus one
  poll"*, with a fake that always says one player.
- **R2 (comparison)**, `src/mscts/run.py:252`: dropping `ValueError` from the
  Comparison's `except` survives. Test: *"a Comparison that raises ValueError
  is an `error` naming it"* (e.g. a Group whose Mask on a packet makes
  `_test_case` refuse a path, or monkeypatch `compare`).
- **C7 (comparison)**, `src/mscts/compare.py:755`: letting `EACH` match a key
  survives, so a Mask on a key beside a list of entity ids
  (`remove_entities.entity_ids.x`-like paths of a list of records) would be
  refused. Test: *"a Mask on a named field of each record in a list that also
  holds an entity id is kept"*, or a parametrized case in
  `test_a_mask_beside_or_around_an_entity_id_is_kept`.

### Low

- **L1 (timing). An `until` window's end is a race for every Bot but the
  first.** `src/mscts/group.py:343-365`. The close Mark is the earliest
  arrival "over all the Bots", but arrival is when each Bot's reader read
  its socket: the readers run one after another, so another Bot's packets that
  reached its socket before the `until` packet can be stamped after it, and a
  Bot that is still taking its own later chunk batches can end the window with
  its own `chunk_batch_finished`. Fix: `observe(until=..., bot=...)`, the
  window ending at that Bot's packet, and a docstring line saying the other
  Bots' cut is timing.
- **L2 (timing). The drain fails the Group for a Bot the server
  disconnected.** `src/mscts/group.py:367-381`, `src/mscts/bot.py:420-428`.
  A Bot kicked by the server (a Group that tests a kick) is still `in_play`
  (its send State is play), so the barrier and the drain raise
  `ConnectionClosedError` on both sides: `error`. Fix: skip a Bot whose reader
  has ended and whose queue is empty, or document that such a Group closes the
  Bot before its window ends.
- **L3 (timing). A failed Control join leaves `control` in the Bot table.**
  `src/mscts/group.py:168-175`, `:237-241`. If `join` or the first `sync`
  raises and the Group catches it, the next `control.run` raises
  `ValueError("the Group already has a Bot called 'control'")`, a harness
  `error`. Fix: close the Bot and drop it from `_bots` on failure.
- **L4 (timing, drift). Settle's "a server that never answers costs two" is
  not what happens.** `src/mscts/settle.py:80-95`, `docs/PLAN.md:1109-1117`. A
  poll that times out counts as empty, so `until_no_player_online` returns
  after one slow poll, even past its deadline, with players maybe still online.
  Either say so ("a server that stops answering counts as empty"), or count a
  timeout as "still online" until the deadline.
- **L5 (comparison). A missing or extra entity before others shifts every
  later number.** `src/mscts/compare.py:655-688`. One `unexpected`
  `add_entity` turns every later entity reference into a `field` Divergence
  too, so `Verdict.differing` names test cases that agree. Not wrong, but it
  inflates the per-test-case score against the Candidate. H2's naming by
  `add_entity` fixes this for spawned entities.
- **L6 (comparison). A Mask on a parent of an entity id is allowed and hides
  it.** `src/mscts/compare.py:147-153`, `test_a_mask_beside_or_around_an_entity_id_is_kept`.
  Intended (the parent may hold more than ids), but a Mask's reason is the
  only guard; say so in the Mask docstring.
- **L7 (timing). A probe's `RecursionError` aborts readiness.** `status_probe`
  documents "anything else raises" for a wrong server, but a `RecursionError`
  out of `json.loads` is not a statement about the server's identity. H3(a)
  fixes it.

### Drift

| Where | Code | Docs | Note |
| --- | --- | --- | --- |
| ADR-0010 amendment #88 item 2 | gap as proof | "a wait between the requests proves nothing" | True of the gap, not of the wait as proof (H1) |
| CONTEXT "Observation window" | close Mark after every Bot's barrier | "each Bot in play first passes the barrier" | Silent on the shared close (MD2) |
| `group.py:70`, guide line 64 | `PlayersStillOnline` → `error` | "wait with settle" | H4 |
| PLAN 1109-1117, `settle.py:80-82` | a timed-out poll counts as empty | "a server that never answers costs two" | L4 |
| ADR-0010 #105 item 1 | earliest read time over Bots | "the first such play packet arrived at a Bot" | L1 |
| `tests/compare/test_entity_ids.py` docstring, CONTEXT "Mask" | first-appearance numbering in the windows | "a packet about another entity is still a Divergence" | Not for entities spawned before the window (H2) |
| `group.py` `_sync` | Control's Bot passes every window's barrier | ADR-0010 item 4 "every Bot in play" | Consistent, but wasted: Control's packets are never compared (G13 survives as equivalent) |

## Checked and found sound

The next audit can skip these unless the code changes:

- **Stamps and ties.** One read's frames are stamped `t0, t0+1, ...` in wire
  order; the next read's stamp is always later (decoding a frame takes far
  more than a nanosecond), and `Transcript.record`'s "in the future" check
  cannot trip on them. The `until` close Mark at arrival + 1 and Compare's
  `bisect_right` rule (a packet stamped at a Mark's time is after it) agree:
  the next frame of the same read is outside, the `until` packet inside.
  `observe:open` uses the same rule (a packet stamped at the open time is
  inside), and so does `_arrival_of`'s `>= since`.
- **The drain.** `recv(timeout_s=0)` returns a queued Packet without
  suspending, and a cancelled `Queue.get` loses no item; a frame the reader has
  not yet read is stamped after the Mark anyway, so the drain never decides
  what a window holds.
- **Sides are played one after the other** (`_Instances.play`), so the other
  side's decoding never shares the loop with a barrier. (Within a side, H1
  still applies.)
- **The marker token.** `mscts-barrier-<n>` counts up per Control, so a
  token can only be the prefix of a later one, which cannot have arrived
  first; `Control.run`'s evidence and command tree are both filtered by
  arrival time, so a Bot that left contributes nothing.
- **Compare against hostile values.** The deepest value the codec decodes
  (331 levels of mob effect details, one more is "nested too deeply") compares
  without a `RecursionError` (`probe_deep_value.py`: "compare: mismatch 1").
  `_strict_json` and `status_version` catch `ValueError` and
  `RecursionError`; `_nesting` is iterative. NBT is kept as bytes.
- **Alignment** is a deterministic LCS, mirrored when the sides swap; an
  out-of-order Candidate gets `missing` and `unexpected` pairs, never a silent
  match.
- **Masks.** A Mask on an entity id, on a list of them, or on an indexed
  element of one is refused in every State; `RANDOM_FIELDS` are masked before
  the Group's Masks and each has its evidence (ADR-0011); a Mask's path must
  be spelled as a Divergence path.
- **`UNORDERED`.** The sorts are stable (a duplicate name keeps the client's
  last-wins order), a tag's `entries` keep their order, and a malformed list
  is left as it came rather than raising.
- **Network traffic vs gameplay.** Only packets with a canonical form can
  have a network traffic Divergence, only where the unmasked canonical values
  are equal, and `match` still needs none (ADR-0007).
- **`judge`.** Reference failure → `error`; Candidate `CommandMissing` →
  `blocked`; Candidate `CANDIDATE_FAILURES` → `mismatch` led by `failed`,
  then the Comparison of what was recorded; a Comparison that raises →
  `error`. `_sync` unwraps the TaskGroup's ExceptionGroup to the failing Bot's
  own error, so `raised_by` names it.
- **Cleanup.** `run_group` closes every Bot in `finally`; Control's old Bot is
  closed by `leave` before it is replaced; settle never cancels a poll from
  outside (but see H3 on `gather`).

## Mutation log

The whole batch ran as
`python3 scripts/mutate.py --batch scratchpad/mutants.json --jobs 2 --timeout 300 -- tests/net tests/group tests/compare tests/run tests/codec/test_entity_ids.py tests/test_transcript.py -m 'not reference and not selfcheck and not candidate and not statistical' -x -q -p no:randomly`,
after one green baseline of that selection. Paths are under `src/mscts/`.
"Killed" means pytest ran the selection and at least one test failed (exit 1).
`⏎` marks a newline inside a replacement; indentation is left out here, and
`mutants.json` has the exact strings. `git status` was clean afterwards (batch
mode mutates throwaway copies).

| Id | File | Old | New | Result |
| --- | --- | --- | --- | --- |
| N1 | `net.py` | `t_ns += 1 # the next frame` | `t_ns += 0 # the next frame` | killed |
| N2 | `net.py` | `self._last_arrival_ns = item.t_ns` | `self._last_arrival_ns = self._transcript.now_ns()` | killed |
| N3 | `net.py` | `chunk = await self._reader.read(_READ_SIZE) ⏎ t_ns = self._transcript.now_ns()` | `t_ns = self._transcript.now_ns() ⏎ chunk = await self._reader.read(_READ_SIZE)` | killed |
| B1 | `bot.py` | `if second - first >= round(TICK_GAP_S * 1e9):` | `if second - first > round(TICK_GAP_S * 1e9):` | **survived** (equivalent in practice: two stamps exactly 5,000,000 ns apart) |
| B2 | `bot.py` | `if second - first >= round(TICK_GAP_S * 1e9):` | `if second - first >= round(TICK_GAP_S * 1e9) // 2:` | **survived** (missing test) |
| B3 | `bot.py` | `await asyncio.sleep(TICK_GAP_S)` | `pass` | killed |
| B4 | `bot.py` | `if trips >= SYNC_MAX_TRIPS:` | `if trips > SYNC_MAX_TRIPS:` | killed |
| B5 | `bot.py` | `trips += 2` | `trips += 1` | killed |
| B6 | `bot.py` | `return cast("int", self._connection.last_arrival_ns)` | `return self._connection.transcript.now_ns()` | killed |
| B7 | `bot.py` | `second = await self._ask_for_statistics()` | `second = first` | killed |
| G1 | `group.py` | `t_ns=self._arrival_of(until, since=opened) + 1)` | `t_ns=self._arrival_of(until, since=opened))` | killed |
| G2 | `group.py` | `if event.t_ns >= since ⏎ and event.bot != CONTROL_PLAYER` | `if event.t_ns >= 0 ⏎ and event.bot != CONTROL_PLAYER` | killed |
| G3 | `group.py` | `and event.bot != CONTROL_PLAYER ⏎ and event.packet.name == name` | `and True ⏎ and event.packet.name == name` | killed |
| G4 | `group.py` | `return min(arrivals)` | `return max(arrivals)` | killed |
| G5 | `group.py` | `await self._sync() ⏎ self._mark(OBSERVE_CLOSE)` | `self._mark(OBSERVE_CLOSE)` | killed |
| G6 | `group.py` | `else: ⏎ await self._drain()` | `else: ⏎ pass` | killed |
| G7 | `group.py` | `and event.t_ns >= since ⏎ and event.packet.direction is Direction.CLIENTBOUND ⏎ and event.packet.name == _SYSTEM_CHAT` | `and event.t_ns >= 0 ⏎ and event.packet.direction is Direction.CLIENTBOUND ⏎ and event.packet.name == _SYSTEM_CHAT` | killed |
| G8 | `group.py` | `and event.packet is not marker` | (deleted) | killed |
| G9 | `group.py` | `and event.t_ns >= self._joined_ns # not the tree a Bot that left was sent` | `and event.t_ns >= 0` | killed |
| G10 | `group.py` | `await bot.sync() ⏎ return tuple(` | `return tuple(` | killed |
| G11 | `group.py` | `await bot.join() ⏎ await bot.sync()` | `await bot.join()` | killed |
| G12 | `group.py` | `self._joined_ns = self._transcript.now_ns()` | `pass` | killed |
| G13 | `group.py` | `if bot.in_play: ⏎ barriers.create_task(bot.sync())` | `if bot.in_play and bot.name != "control": ⏎ barriers.create_task(bot.sync())` | **survived** (equivalent: Control's packets are never compared) |
| S1 | `settle.py` | `if reading is None or reading.online == 0:` | `if reading is None or reading.online < 2:` | killed |
| S2 | `settle.py` | `if loop.time() >= deadline:` | `if loop.time() >= deadline + 1:` | **survived** (missing test) |
| S3 | `settle.py` | `if not isinstance(online, int) or isinstance(online, bool):` | `if not isinstance(online, int):` | killed |
| C1 | `compare.py` | `if packet.name in HEARTBEAT:` | `if False:` | killed |
| C2 | `compare.py` | `latest = bisect.bisect_right(self.times, event.t_ns) - 1` | `latest = bisect.bisect_left(self.times, event.t_ns) - 1` | killed |
| C3 | `compare.py` | `if not _is_player(packet.fields):` | `if True:` | killed |
| C4 | `compare.py` | `"tagged_registries": _sorted_by(sorted_tags, "registry")}` | `"tagged_registries": sorted_tags}` | killed |
| C5 | `compare.py` | `return {**registry, "tags": _sorted_by(tags, "tag_name")}` | `return registry` | killed |
| C6 | `compare.py` | `if self.path != WHOLE_PACKET and _is_entity_id(` | `if False and _is_entity_id(` | killed |
| C7 | `compare.py` | `return type(step) is int if isinstance(key, Each) else step == key` | `return True if isinstance(key, Each) else step == key` | **survived** (missing test) |
| C8 | `compare.py` | `if not keys or not isinstance(keys[-1], Each):` | `if True:` | killed |
| C9 | `compare.py` | `return {event.bot for event in transcript.events} - {CONTROL_PLAYER}` | `return {event.bot for event in transcript.events}` | killed |
| C10 | `compare.py` | `if next(_diff(*canonical, path), None) is None:` | `if True:` | killed |
| C11 | `compare.py` | `if _in_more_than_one_state(packet):` | `if False:` | killed |
| C12 | `compare.py` | `indexed = _Masks.of((*_RANDOM_MASKS, *masks))` | `indexed = _Masks.of(tuple(masks))` | killed |
| C13 | `compare.py` | `return narrowed is not None and (not narrowed or packet.name in narrowed)` | `return narrowed is not None` | killed |
| C14 | `compare.py` | `numbers = _Numbers.of(taken)` | `numbers = _Numbers.of(e.packet for e in transcript.events if e.bot == bot and e.packet.direction is Direction.CLIENTBOUND)` | killed |
| C15 | `compare.py` | `numbers.ids.setdefault(found, f"#{len(numbers.ids) + 1}")` | `numbers.ids.setdefault(found, f"#{found}")` | killed |
| E1 | `codec/entity_ids.py` | `if found and key in cut:` | `if False:` | killed |
| E2 | `codec/entity_ids.py` | `return (EACH,), SERIALIZERS` | `return None` | killed |
| R1 | `run.py` | `TimeoutError, # no answer in time` | (deleted) | killed |
| R2 | `run.py` | `except (TypeError, ValueError) as exc:` | `except TypeError as exc:` | **survived** (missing test) |
| R3 | `run.py` | `divergences=(failed, *verdict.divergences),` | `divergences=(failed,),` | killed |
| R4 | `run.py` | `outcome=Outcome.MISMATCH, ⏎ divergences=(_failed(bot="", what=str(candidate)),),` | `outcome=Outcome.ERROR, ⏎ divergences=(_failed(bot="", what=str(candidate)),),` | killed |
| R5 | `run.py` | `if isinstance(candidate, GroupError) and isinstance(candidate.__cause__, CommandMissing):` | `if False:` | killed |

Total: 48 mutations, of which 42 were killed and 6 survived (4 missing tests,
MD4, and 2 equivalent). Every window, until, Control, entity-numbering,
heartbeat, `UNORDERED`, network-traffic and Verdict-rule branch tried was
killed; the survivors are a threshold value (B2), a deadline (S2), an
`except` clause (R2) and a Mask-refusal corner (C7).

## Proposed order of work

1. **Before #30 (the join Group) is briefed**, one small PR for H3 and H4,
   both in the Verdict rule: `_json_object` catches `ValueError` and
   `RecursionError`; `_left` turns any poll failure into the Candidate's
   `failed` Divergence; `PlayersStillOnline` joins `CANDIDATE_FAILURES`. Tests
   first, as written above, plus the R2 test (MD4). Add "every `json.loads`
   of server text catches ValueError and RecursionError" to the audit
   checklist.
2. **The barrier (H1, H5, with B2 from MD4)**: a decision comment on an
   ADR-0010 amendment replacing the gap as proof with the wait as proof, and
   matching each answer to its own request. Brief it with the barrier rule
   (20 of 20 Self-checks five times in a row, under `repeat.py --stress`) and
   `probe_stall.py`'s threaded fake as its first test. This is the one that
   can make Self-checks flaky under load today, invisibly.
3. **Entity numbering (H2, MD3, L5)**, before any Group spawns entities in its
   setup and acts on them in a window: name an id by its `add_entity` (type and
   position) when that is outside the windows, and end a number at
   `remove_entities`. Update the docstring of `tests/compare/test_entity_ids.py`
   and CONTEXT's Mask entry ("a packet about another entity is still a
   Divergence") to say exactly when that holds.
4. **Window hygiene (MD1, MD2, L1)**, in the next Group-machinery brief:
   `observe` validates names against the Target's play packets and
   `HEARTBEAT`; per-Bot close Marks; `until` names its Bot. MD2 and L1 need an
   ADR-0010 amendment.
5. **The rest (S2 and C7 from MD4, L2, L3, L4, L6, L7)** as each module is next
   touched; L4 is a one-line doc fix in PLAN and `settle.py`.
