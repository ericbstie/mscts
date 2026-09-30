---
name: Test proposal
about: A new Group that plays one mechanic against vanilla and a Candidate
labels: spec, test
---

<!-- A test is a Group (a Scenario until #7 lands): actions played against both
     servers. Its test cases are automatic: every field it compares is one (#8).
     Title: `<mechanic>/<name>: <what a player would notice>`.
     Read "Proposing a test" in docs/contributing.md first. File paths below are
     the pre-#7 names (scenarios/ becomes the Groups package). -->

## What a player would notice

<!-- The mechanic, and what goes wrong in the game when a server gets it wrong.
     One short paragraph, in plain words. -->

## Evidence

<!-- What vanilla does, and where servers are known to differ, with a source for
     each: a line in docs/research/, a Paper/Spigot/Pumpkin config option or doc
     page, a Mojang bug id. Mark what you observed yourself as verified. -->

## The Group

- **Id**: `<mechanic>/<name>` (one line per Group if the issue adds several)
- **Kind**: exact | tick-exact | statistical
- **ServerSpec**: the overrides, or "default"
- **Fixture**: vanilla commands, in order (game rules by their 26.3 ids)
- **Script**: what each Bot does, in order
- **Compared**: the packets (and fields) whose test cases this Group
  produces, and why a player sees them
- **Masks**: each with the reason it has no gameplay meaning, or "none"

## Determinism

<!-- What could differ between two vanilla runs (randomness, wall-clock timing,
     entity ids, the join spawn spread) and how the Group pins it. The Self-check
     must match in 20 runs out of 20; a statistical Group's must not reject. -->

## Needs

<!-- The enabler issues this depends on, and the protocol facts to verify first
     (protocol-research skill). "none" if it runs on what exists. -->

## Acceptance tests

- [ ] `tests/scenario/test_<mechanic>.py`: the Group is registered with its
      kind, Masks and prerequisites, and its script sends what it should
      against a fake server
- [ ] reference tier: the Self-check matches in 20 runs out of 20
- [ ] candidate tier: `mscts run --candidate pumpkin --group '<mechanic>/*'`
      completes (its differences are reported, never asserted)

## Docs delta

<!-- The row for the Groups reference page (docs/reference/scenarios.md until
     #7 renames it) and the test case entries (#12), verbatim. -->

## Owns

- `src/mscts/scenarios/<mechanic>.py` (new)
- `tests/scenario/test_<mechanic>.py` (new)
- the `<mechanic>` section of the Groups reference page

## Out of scope

-
