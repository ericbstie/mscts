# ADR-0002: Python with the Astral toolchain, managed by mise

Status: accepted (2026-09-25)

## Context

The work is hundreds of tiny red/green iterations, so the time per loop
dominates. A codec, process orchestration, diffing and reporting are all
I/O-bound or table-driven, so raw language speed matters little. The same
client measures both servers, so client overhead cancels out in
Comparisons.

## Decision

- Python 3.13 in a `src/` layout, packaged with **uv**.
- **ruff** with `select = ["ALL"]`, which covers lint, format and import
  order. The only ignores are rules that conflict with each other or with
  the formatter, and each one gets a justification comment.
- **ty** for type checking, with every diagnostic promoted to an error.
- **bandit** for security lint over `src/`.
- **pytest** for the dev test Tiers, selected by markers.
- **mise** pins the tool versions (Python, uv, Java 25 for the Reference)
  and defines the tasks (`mise run check`, …).

## Consequences

- Large bot swarms for load tests may need `asyncio` tuning, or a native
  helper later. We will revisit when a Measurement shows the client is the
  bottleneck.
- ty is pre-1.0. If a ty upgrade breaks `check`, pin it rather than
  loosening the rules.
