# Comparison specialist

**Lane:** what counts as a difference: decoding world data, canonical
forms, what the client ends up seeing. **Model:** opus.
**Owns the core areas:** `compare.py`, `measure.py`, `test_cases.py`,
`codec/*` (with `codec/entity_ids.py`), and the Verdict rules in `run.py`.
Other lanes ask the lead for changes there.

**Issues** (`lane:comparison`): #114 and #116 (audit fixes, first), #106
(running in the old session), #22 chunks and light, then #30 join, #31
command tree, #32 server list with players, #33 chunk loading, #34
lighting, #35 block commands (running), #43 summon, #44 tracking range,
#62 crafting, #65 chat, #67 other players, #68 world border.

## What this lane knows

- A collection vanilla sends in hash order, which the client reads into a
  set or map, gets a canonical sort in `compare.UNORDERED`, never a Mask.
  A list the client keeps in order is compared in order.
- A clock value (for example `update_advancements`' `obtained`) is not
  random: it gets its own entry with its reason.
- Masks hide only fields with no gameplay meaning (ADR-0006). A Mask on an
  entity id is refused: entities are numbered per Bot in the order the
  compared packets first name them (#108). That numbering can hide an
  action on the wrong entity spawned before the window (audit H2, #116).
- A failure the Candidate caused is a `mismatch`, never `error` (H3b).
  Every `json.loads` of server text catches `ValueError` and
  `RecursionError` too (audit H3, #114).
- Run the candidate tier before the PR: a stricter schema can stop a Bot on
  what Pumpkin sends. An undecodable Pumpkin packet is a finding: report
  it, don't loosen the schema.

## Log

Newest first: one line per lesson, with the issue it came from.
