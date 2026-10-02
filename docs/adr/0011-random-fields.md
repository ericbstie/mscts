# ADR-0011: Exact Groups never compare a field vanilla draws at random

Status: accepted (2026-10-01). Refines ADR-0006's Masks rule (item 2) for
fields vanilla draws at random on every run. Amended 2026-10-02 (#106): a
value vanilla reads from its clock is one too, below.

## Context

Some fields hold a value vanilla draws at random each time it sends them.
`login_finished.session_id` is a UUID vanilla draws when its first
connection opens (`ServerConnectionListener.getSessionId`), so two
vanilla Instances never send the same one, and every Group that joins a
Bot differs from itself in its Self-check. The seed of a sound packet
(#29) is another: it picks which variant of a sound a player hears.

Each Group could mask such a field itself. Every Group that joins would
then repeat the same Mask, and a Group that forgot it would fail its
Self-check for a reason that has nothing to do with its mechanic.
ADR-0006 also says a Mask hides only what has no gameplay meaning, and a
sound's seed has some.

## Decision

1. **`compare.RANDOM_FIELDS` lists the fields vanilla draws at random on
   every run**, keyed `<packet>.<path>`, each with a reason that says
   where vanilla draws it. Every Comparison masks them, in any State,
   before its Group's own Masks.
2. **An exact Group never compares a random field**, whether or not a
   player could notice it: two vanilla runs would differ, so the exact
   comparison could never match. How such a field is distributed belongs
   to a statistical Group (#24), as ADR-0006 item 3 says of random
   mechanics.
3. **A field joins the list only with evidence** that vanilla draws it at
   random: the bytecode that draws it, and two vanilla runs that differ in
   it.

`update_tags` is not a random field. Vanilla sends its registries and
tags in an order that changes from one boot to the next, but the client
reads them into maps, so the order is a form of the same value, not a
random one. `compare.UNORDERED` sorts it before anything else.

## Consequences

- A Group lists only the Masks its own actions need.
- A Candidate that sends a constant where vanilla draws at random is not
  reported by any exact Group. Only a statistical Group can catch it.
- Each entry in `RANDOM_FIELDS` is reviewed like a Mask: its reason must
  show that vanilla draws the value at random, not merely that it
  differed once.

## Amendment (2026-10-02, #106): clock values, and presence

A value vanilla reads from its clock differs between two runs as a random
draw does: an advancement criterion's `obtained` time is `Instant.now()`
(javap, `CriterionProgress.grant`), and two vanilla joins differed only in
it. So `RANDOM_FIELDS` holds fields vanilla draws at random or reads from its
clock, with the same evidence rule. Its Masks, like every Mask, hide a value
and never whether it is there: a criterion obtained on one side only is a
Divergence (`compare.MASKED`).
