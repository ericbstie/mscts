# ADR-0003: One pinned Target at a time — 26.3 / protocol 777

Status: accepted (2026-09-25)

## Context

The Reference and the Candidate must speak the same protocol version.
Vanilla's latest release is 26.3 (protocol 777, Java 25), and Pumpkin
nightly speaks 777. Minestom is on 26.2 and FerrumC is on 1.21.8.
Supporting several versions multiplies the codec and Scenario work before
anything works end to end.

## Decision

- Support exactly one Target: **26.3 / 777**.
- The Target is still passed explicitly as a value. Packet data lives
  under a version-keyed path (`src/mscts/codec/data/26.3/`), so adding a second
  Target is an extension, not a rewrite.
- Packet IDs come from the vanilla data generator for that jar and are
  committed. Field layouts come from minecraft.wiki raw wikitext at a
  recorded revision, and each is verified against the Reference in a
  `reference`-tier test.

## Consequences

- Minestom and FerrumC cannot be Candidates until a second Target is
  added.
- Bumping the Target is a deliberate milestone: regenerate data, re-run
  the Self-check, and fix any drift.
