# ADR-0005: In-repo plan tracking; every commit is green

Status: accepted (2026-09-25)

## Context

Work spans many agent sessions, each in a fresh container. The `gh` CLI
is not available there. Bugs will be found later that need `git bisect`.

## Decision

- The plan and progress live in the repo: `docs/PLAN.md` (goals,
  interfaces, milestones) and `docs/PROGRESS.md` (log, next step). They
  change in the same commits as the code they describe.
- One increment per commit, and every commit passes `mise run check`.
  Red tests are never committed. The test and the code that makes it pass
  go in together, so any commit is a valid `git bisect` point.
- Work happens on `main`.

## Consequences

- `git bisect run mise run check` works across the whole history.
- `docs/PROGRESS.md` is the handoff between sessions and must be current
  whenever work stops.
