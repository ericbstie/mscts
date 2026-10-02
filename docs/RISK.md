# Risk register

Owned by the tech lead. It sets how hard each change is reviewed
([PROCESS](PROCESS.md#lanes-and-review-levels)), so the review level is a
rule kept here, not a feeling.

## Review levels now

A change is reviewed at the highest level of its lane and of every core
area its diff touches. The lead may raise one issue a level above that
(new concurrency, a new kind of Verdict, code later Groups build on), never
lower.

| Lane or core area | Level | Clean merges since the last escape | Why |
| --- | --- | --- | --- |
| lane: timing | Rigorous | 0 | Audit 2026-10-02 (`docs/audits/2026-10-02-timing-compare.md`): H1, H5 in the barrier |
| lane: comparison | Rigorous | 0 | Audit 2026-10-02: H2, H3, H4 |
| lane: statistics | Rigorous | 0 | No escapes yet; distributions and their tests are new ground |
| lane: player-actions | Standard | 0 | Starting level |
| core: timing (`net.py`, `bot.py`, `settle.py`, `group.py`, `transcript.py`) | Rigorous | 0 | Five escapes since 2026-09-26, then the audit |
| core: comparison (`compare.py`, `measure.py`, `test_cases.py`, `codec/entity_ids.py`, `run.py` Verdicts) | Rigorous | 0 | Audit 2026-10-02 |
| core: codec (`codec/*`) | Standard | 0 | Audit K MD1, MD4 (2026-09-26); none since |
| core: platform (`runner.py`, `adapters/*`, `install.py`, `registry.py`, `spec.py`, `cli.py`, `report.py`) | Standard | 0 | Audit K H1; orphaned Instances (#3) |
| tooling and docs (`scripts/*`, `docs/*`, `.github/*`) | Light | 0 | Two flaky margins and one silently broken guide example, none harmful |

## Rules

- **An escape raises the level.** A bug found on `main` (by a later
  issue, a tier run, an audit or a user) raises the lane it came from and
  the core area it is in by one level, and resets their clean count.
- **Clean merges lower it.** After 5 merges in a row in that lane or core
  area with no escape, the level drops one step, to Light at the lowest.
- **An escape at Rigorous calls an audit** of that core area, briefed to
  the reviewer.
- A bug caught before merge (by review, a Self-check, a mutation sweep) is
  logged below but raises nothing: that is the review working.

## Bug log

Newest first. "Escaped" means it was on `main`.

| Date | Area | Bug | Found by | Escaped | Follow-up |
| --- | --- | --- | --- | --- | --- |
| 2026-10-02 | core: timing | A stall in the harness looks like a server tick to `Bot.sync` (audit H1) | audit | yes | #115 |
| 2026-10-02 | core: timing | One unrequested `award_stats` shifts every later barrier answer (audit H5) | audit | yes | #115 |
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
