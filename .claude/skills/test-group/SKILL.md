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
`scripts/research/probe_loop.py`'s `run(group, plays, out_dir, workdir)`
the draft Group (it boots both Instances with the Group's own
`spec`, prints the Divergences per test case and saves the whole
Transcripts of failing plays; `loop=` takes a play loop of your own).
Run it in the background and write the unit tests meanwhile: a Group
with ten windows takes 10 to 40 minutes. It answers whether the Group
can match at all. Read every Divergence back to its cause with javap,
in the server (where vanilla makes the value) and in the client (what
it reads it into):

- a list the client reads into a set or map, sent in hash order (per
  boot or per join), needs a canonical sort (`compare.UNORDERED`),
  never a Mask;
- a value vanilla draws at random, or reads from the clock (an
  advancement's `obtained` time), wherever the packet is sent, is a
  `compare.RANDOM_FIELDS` entry; one that is random only for some
  sources (the position and motion of an item a block drops; a spawned
  pig's are not) is a Mask of the Group, with the javap line that draws it;
- an identifier without gameplay meaning is a Mask, with its reason;
- a window that makes several entities at once (a `fill ... destroy`
  that drops four items) can still differ: vanilla resends each new
  entity at the end of the tick in the hash order of its raw id, and
  the two Instances' raw ids differ, so only the order differs (17 of
  20 plays did not match, `blocks/fill`). Make one entity per window, or
  ask the lead for a canonical order;
- a Group that spawns or counts entities turns natural spawning off in
  its Fixture (`gamerule spawn_mobs false`; 26.3 rule names are
  snake_case), and tags what it summons so it removes only those;
- entities a Group spawns before its window are told apart by type and
  position at their first `add_entity` before the window
  (`pig@(1.5, -60.0, 7.5)`, #116): spawn two of one type at different
  positions, or the Comparison cannot tell which one a packet in the
  window is about; an entity that spawns at a random position (a
  dropped item) takes a Mask on that `add_entity` axis, which hides it
  in the name too;
- an entity named by its position must not move before the window:
  summon it with `NoAI:1b`, or run `tick freeze` while the Fixture sets
  it up, or its first `add_entity` can carry a position it drifted to;
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
   A Bot that runs a command itself (an operator: `spec=` adds it to the
   ServerSpec's `operators`) drains before the window and waits for its
   own feedback inside it: `await bot.drain()`, then `async with
   context.observe(...): await bot.command(...); await bot.expect(
   "minecraft:system_chat", timeout_s=...)`. `Bot.sync` alone does not
   cover a chat command on a server behind schedule, and an operator is
   also told every other operator's feedback, which a bare `expect`
   would take for its own (`groups/blocks.py`; its fake server is
   `BlocksServer` in `tests/group/test_blocks.py`).
4. Change blocks only in chunks a Bot has had since it joined
   (`docs/guide/writing-a-group.md`); there is no chunk wait yet.
5. A Group starts with no player online (#97); it never relies on a
   previous Group's state, and leaves the server as it found it: undo
   every setting it changes (`tick freeze` -> `tick unfreeze`, gamerules)
   in a `finally`, because the Self-check tier and `mscts run` play every
   Group on the same two Instances. Push each undo on a
   `contextlib.AsyncExitStack` as its setting is made, so that one that
   fails does not stop the rest. Put a case a Candidate may hang on
   last, so the others are compared first.
6. The kind is `exact` unless the issue says `tick-exact` (#23) or
   `statistical` (#24).
7. A span (`context.span`) ends when its body does, so it can time a
   whole Bot operation (`bot.join()`), not a packet inside one. The
   Report shows no timings (ADR-0012); a Run's results keep them.
8. Not everything a server holds is sent to a Bot that watches it: a
   chest's items are not (only its block state). Read such a value back
   with a command (`data get block <pos> Items`) in a window of its own,
   and compare the feedback.

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
   never what a server answers. A fake that answers late, or that sees a
   Bot leave with something unread (the connection resets), flakes one
   run in 25 to 40 under load: run the file through `python3
   scripts/repeat.py --times 40 --stress -- tests/group/test_<mechanic>.py`
   before the push (red-green, Known traps).
2. Self-check: the registry tier (#84) covers a Group once registered.
   Before each push: `mise run test:selfcheck -- -k '<mechanic>/'`.
   Once, for the PR: `MSCTS_SELFCHECK_REPEAT=20` on the new Groups.
3. Candidate evidence: `uv run mscts run --candidate pumpkin --group
   '<mechanic>/*'`, its Report in the PR body. A Divergence there is
   what the suite is for, not a failure. Run each Group alone too
   (`--group '<id>'`): a Candidate that hangs on one Group is not
   restarted, so the next Group of the same Run fails with a timeout that
   is not its own.
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
