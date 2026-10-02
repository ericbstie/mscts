---
name: test-group
description: How a `test` issue becomes Groups, the same way every time. Use when briefing, working on or reviewing any issue labelled `test` (#30–#72).
---

# test-group

Every `test` issue lands by this routine. A Group that seems to need a
new mechanism is a finding for the lead, not something to build inside
a test PR.

## First: measure, before any code

Play a draft of the Group 20 times on two fresh vanilla Instances
before writing it in `src/`: a script in your scratch dir that hands
`scripts/research/probe_loop.py`'s `run` a loop of its own (assign
`probe_loop.loop` until #107 adds `loop=`), printing
every Divergence and saving failing Transcripts. It costs about 15
minutes and answers whether the Group can match at all. Read every
Divergence back to its cause with javap, in the server (where vanilla
makes the value) and in the client (what it reads it into):

- a list the client reads into a set or map, sent in hash order (per
  boot or per join), needs a canonical sort (`compare.UNORDERED`),
  never a Mask;
- a value vanilla draws at random, or reads from the clock (an
  advancement's `obtained` time), is a `compare.RANDOM_FIELDS` entry;
- an identifier without gameplay meaning is a Mask, with its reason;
- anything else is the Group not being deterministic yet: the window
  reaches timing (later chunk batches, a barrier that waits ticks) or
  world state that drifts between Instances (the default flat world
  has passive mobs near spawn, and they wander).

If a cause needs a schema, a canonical rule or a window option that
does not exist, stop: comment on the issue with the evidence and the
options (`needs-decision`), and report.

## Where things go

- Groups go in `src/mscts/groups/<mechanic>.py`, one module per mechanic
  (the id's first segment), imported in `src/mscts/groups/__init__.py`.
  Ids exactly as the issue names them.
- World setup shared by two Groups goes in `src/mscts/groups/_world.py`,
  made by the second Group that needs it. A helper used once stays in
  its Group's module. Never two copies of one helper.
- A packet that does not decode is an enabler's job (#22, #29, ...):
  stop and report it, never add a schema in a test PR.
- Comparison rules never live in a Group module. A Mask goes in the
  Group's `masks`, a field vanilla draws at random in
  `compare.RANDOM_FIELDS`, each with its reason and the Self-check
  evidence that needed it.

## Shape of a Group

1. Join the Bots it needs.
2. Set up with `context.control.run(...)` before any Observation window.
   Keep setup small.
3. Act inside `async with context.observe(<packet names>):`. On exit
   every Bot in play passes the barrier (`Bot.sync`, ADR-0010); only
   what the named Bots receive inside windows is compared. Name the
   packets the Group tests: an unnarrowed window also compares whatever
   the world sends meanwhile (mobs entering view, chunk batches).
4. Change blocks only in chunks a Bot has had since it joined
   (`docs/guide/writing-a-group.md`); there is no chunk wait yet.
5. A Group starts with no player online (#97); it never relies on a
   previous Group's state, and leaves the server as it found it: undo
   every setting it changes (`tick freeze` -> `tick unfreeze`, gamerules)
   in a `finally`, because the Self-check tier and `mscts run` play every
   Group on the same two Instances.
6. The kind is `exact` unless the issue says `tick-exact` (#23) or
   `statistical` (#24).
7. A span (`context.span`) ends when its body does, so it can time a
   whole Bot operation (`bot.join()`), not a packet inside one. The
   Report shows no timings (ADR-0012); a Run's results keep them.

What a Candidate does wrong is the Report's job, never the Group's:
a command it lacks gives `blocked` (`CommandMissing`), a packet it sends
that does not decode raises `CodecError` and fails that Bot. Known:
Pumpkin answers commands out of order (#17) and stalls on
`fill ... destroy`. A join may repeat its first `player_position` (a
race with the first tick, docs/research/2026-09-26-join.md). By javap,
`gamerule player_movement_check false` turns off the check that makes
the repeats, and Pumpkin accepts the command; a window that holds a
join sets it in its Fixture.

## Tests, red first

1. Unit: `tests/group/test_<mechanic>.py` against the fake server. Pin
   what each Bot sends and in which order, the windows and the Marks;
   never what a server answers.
2. Self-check: the registry tier (#84) covers a Group once registered.
   Before each push: `mise run test:selfcheck -- -k '<mechanic>/'`.
   Once, for the PR: `MSCTS_SELFCHECK_REPEAT=20` on the new Groups.
3. Candidate evidence: `uv run mscts run --candidate pumpkin --group
   '<mechanic>/*'`, its Report in the PR body. A Divergence there is
   what the suite is for, not a failure.
4. A Self-check that does not match is never fixed by a retry or a
   larger repeat. Find its cause as in "First" above.

## Docs, same PR

- `docs/reference/groups.md`: the mechanic's section, one row per Group
  (Id, Kind, Requires, What it does, Measurements); remove its Planned
  row.
- Test case titles (#12's `TITLES`) for each compared path the Report
  shows.
- The issue's Docs delta, verbatim.

## Done

One PR per issue, titled `group: <mechanic>: <what it compares>`, with
`Closes #n`. Its body has the 20-of-20 Self-check, the Pumpkin Report
and the javap facts the Groups rely on.
