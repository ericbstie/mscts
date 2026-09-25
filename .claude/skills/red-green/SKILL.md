---
name: red-green
description: The mscts development loop. Use for ANY code change in this repo (new feature, fix, refactor, new Scenario or Adapter) and when starting or ending a work session, to pick the next increment from docs/PROGRESS.md, drive it test-first, commit it green, and hand off.
---

# red-green

mscts is built by hundreds of tiny, always-green increments. One increment
is one behaviour: one failing test, then the least code that makes it pass,
then one commit.

## Orient (start of session or after a context reset)

1. Read `docs/PROGRESS.md`. Its **Next** list is the queue.
2. Skim `CONTEXT.md`, the vocabulary. Read the `docs/PLAN.md` interface
   section for the module you will touch.
3. Run `git log --oneline -15` and `mise run check`. If check is red on a
   clean tree, fixing that is the increment.

## Loop

1. **Pick** the first item under Next. If you cannot state it as one
   failing test, split it and write the split back into PROGRESS.md.
2. **Red.** Write the test. Run only that test (`uv run pytest path::name`)
   and confirm it fails for the expected reason: an assertion, or the
   missing name. A test that errors for some other reason is not red yet.
3. **Green.** Write the minimum code. Do not add code for a later
   increment, and do not add options nobody asked for.
4. **Refactor** while green, if the code now reads worse than the code
   around it.
5. **Check.** `mise run check`. If you touched anything server-facing
   (codec schemas, adapters, runner, Bot, Scenarios), also run
   `mise run test:reference`.
6. **Commit** the test and the code together:
   `git commit -m "<area>: <imperative summary>"`, where area is one of
   `codec`, `net`, `bot`, `spec`, `adapter/<name>`, `runner`, `scenario`,
   `compare`, `measure`, `report`, `cli`, `docs` or `tooling`. Add a body
   only when the why is not obvious. End every message with the
   attribution trailer the session provides.
7. Repeat. **Workers** (subagents) stop here. They never push or edit
   `docs/PROGRESS.md`; they end with the Worker report in
   `docs/PROCESS.md`. **The tech lead**, every 3–5 commits and always
   before stopping, updates `docs/PROGRESS.md` (Log and Next) in its own
   `docs:` commit, then runs `git push -u origin main`.

## Rules

- **Never commit red.** Every commit must pass `mise run check`, so
  `git bisect run mise run check` works across the whole history.
- A new domain term goes into `CONTEXT.md` in the same commit that
  introduces it. A changed interface goes into the PLAN.md interface
  section in the same commit. A reversed decision gets an ADR.
- Protocol facts (IDs, layouts, behaviour) come only from the sources in
  the `protocol-research` skill, and a `reference`-tier test pins them.
- Never loosen ruff, ty or bandit to get green. Fix the code. If a rule
  is truly wrong for this repo, add a targeted per-file ignore with a
  justification comment, in its own `tooling:` commit.
- Unit tests must not touch the network or spawn processes. Put those
  tests in a tier: `@pytest.mark.reference` or `@pytest.mark.candidate`.

## When stuck

- If a test fails in a way you don't understand, shrink the reproduction
  before changing code.
- If a regression appeared at some point in history, run
  `git bisect start <bad> <good>` then
  `git bisect run uv run pytest <test>`.
- If you are going in circles, `git stash` back to the last green commit
  and take a smaller step.
