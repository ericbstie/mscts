# ADR-0007: Network traffic Divergences are reported separately

Status: accepted (2026-09-26)

## Context

Some differences exist only in the bytes the servers send: the vanilla
client decodes both forms identically, so no player can ever notice them.

- Pumpkin sends `"players": {…, "sample": []}` where vanilla omits
  `sample`. The client reads a missing list as empty.
- A text component can be sent as `"x"` or as `{"text": "x"}`.

Until now, Canonicalization erased such differences entirely. That is at
odds with ADR-0006's goal of surfacing every difference. But counting
them like gameplay differences would bury the catalogue in noise.

## Decision

- The Comparison reports every difference. A Divergence whose two values
  are equal after Canonicalization is classified **network traffic**.
  Every other Divergence is **gameplay**.
- The Report lists network traffic Divergences in their own section.
  Compliance scores count only gameplay Divergences.
- Canonicalization becomes a classifier, not an eraser. Its registry now
  also covers "declared defaults": a field the vanilla client treats as
  its default when absent (e.g. `players.sample` ≡ `[]`,
  `enforcesSecureChat` ≡ `false`, `description` ≡ `""`), each cited from
  the client's decoder.

## Consequences

- `Divergence` gains an observability classification. `compare()` diffs
  the raw values and the canonical values: raw-different but
  canonical-equal means network traffic.
- A Verdict whose only Divergences are network traffic is still
  `mismatch`, but the Report scores it as compliant. Whether that needs
  its own Outcome is settled in the M2 wiring brief.
- A Self-check must still be an exact `match`, with no network traffic
  Divergences either, because vanilla against vanilla sends identical
  bytes.
