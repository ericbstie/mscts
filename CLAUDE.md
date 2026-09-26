# mscts

Minecraft Server Compliancy Test Suite. It runs the same scripted client
behaviour against vanilla (the Reference) and a custom server (a
Candidate), diffs what comes back over the wire, and times both.
Server-agnostic by design: see `docs/adr/0001-black-box-differential-testing.md`.

## Start here

- `docs/PROGRESS.md`: where things stand, and the **Next** queue.
- `docs/PROCESS.md`: the tech-lead/worker operating model, retrospective log and process changelog.
- `docs/PLAN.md`: goals, the exact interfaces, tiers and milestones.
- `CONTEXT.md`: the vocabulary. Use its terms exactly.
- `docs/adr/`: decisions. Flag any change that contradicts one.
- `docs/research/`: verified protocol and server facts.

## Operating model

The main session is the **tech lead**. Load the `tech-lead` skill and
follow `docs/PROCESS.md`: brief opus/sonnet worker subagents, integrate
their green commits into `main`, and turn their retrospectives into
process changes. Workers follow the Worker contract in `docs/PROCESS.md`.

## How to work

Use the `red-green` skill for every change: one failing test, the minimum
code, `mise run check`, one commit, repeat. Use the `protocol-research`
skill before encoding any protocol or server fact.

Work on `main`. Never commit red: every commit passes `mise run check`.

## Commands

```sh
mise install && mise run sync   # toolchain + deps (the SessionStart hook does this on the web)
mise run check                  # lint, format check, ty, bandit, unit tier (must be green to commit)
mise run fix                    # ruff format + autofix
mise run install:reference      # install vanilla 26.3 into the shared cache (explicit; a no-op if there)
mise run test:reference         # tests against a live vanilla 26.3 Instance (Java 25)
mise run test:candidate         # tests against a live Candidate Instance
uv run pytest path::test_name   # a single test
```
