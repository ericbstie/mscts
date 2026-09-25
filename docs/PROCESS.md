# Process

How mscts gets built. The main session acts as **tech lead** and delegates
the implementation work to **worker** subagents. Every worker ends with a
retrospective. The tech lead turns those retrospectives into changes to
this process, the skills, the plan or the goals. The process is itself a
product that we keep optimising.

This file is owned by the tech lead. It changes only through the
[changelog](#process-changelog) at the bottom.

## Roles

**Tech lead (the main session).**
- Owns the queue (`docs/PROGRESS.md`), `docs/PLAN.md`, the ADRs, this
  file, and the skills.
- Writes briefs, chooses the model, and spawns workers.
- Reviews and integrates the workers' commits into `main`, then pushes.
- Reads every retrospective and decides what to change.
- Sends work to refactoring or auditing when retrospectives or reviews
  show drift.
- Writes product code only for trivial integration fixes. Anything more
  goes in a brief.

**Worker (a subagent).** Executes exactly one brief, following the
`red-green` skill, in an isolated git worktree. It commits each increment
green, does not push, and ends with the [report](#worker-report).

## Choosing the model

| Model | Use for |
| --- | --- |
| `opus` (Opus 5.5) | Heavy or critical-to-get-right work: interfaces; process lifecycle and concurrency (runner, Connection, Bot); the Comparison engine; Masks and canonicalization; audits; refactors across modules; anything where a subtle mistake would silently corrupt Verdicts or Measurements. |
| `sonnet` (Sonnet 5) | Well-specified, mechanical work: wire types from sample tables, packet schemas from wiki tables, Adapter config translation from an explicit field list, docs. |

When unsure, use `opus`. A wrong Verdict costs more than a slower worker.

## Cycle

1. **Plan a batch.** Choose 1–3 briefs from Next that touch disjoint
   modules, so they can run in parallel without conflicts.
2. **Brief and spawn** each one in the background with worktree
   isolation, using the [template](#brief-template).
3. **Integrate** each branch as it finishes:
   - Review the diff against the PLAN interfaces. Check that the tests
     would fail without the code, that no lint, type or security rule was
     loosened, and that the vocabulary matches `CONTEXT.md`.
   - Rebase onto `main` with every commit re-checked:
     `git rebase main -x "mise run check"`.
   - Fast-forward `main` and push.
4. **Retrospective intake.** Log every item in the
   [retrospective log](#retrospective-log) and decide one of:
   - **adopt**: change the skill, PLAN, PROCESS or goal now, in a
     `docs:` or `tooling:` commit;
   - **defer**: add it to Next;
   - **reject**: record why.
5. **Update `docs/PROGRESS.md`** (Now, Next, Log) and push.
6. **Audit or refactor** after about every third batch, and sooner if
   retrospectives repeat a complaint or a review finds drift. An
   audit is an `opus` brief that reads a key feature end to end against
   PLAN, ADRs and the Reference, and reports findings before changing
   anything.

## Brief template

```
You are a worker on mscts (repo at your cwd, a git worktree of main).
Read CLAUDE.md, docs/PROCESS.md (Worker contract + Worker report), and the
red-green and protocol-research skills before starting.

Goal: <one sentence, in CONTEXT.md vocabulary>
Increments (in order, one commit each): <numbered list, each a single failing test>
Interfaces: <PLAN.md section(s) to implement exactly; allowed deviations>
Out of scope: <what not to touch>
Done when: <observable condition, e.g. `mise run check` green + named tests exist>
Context: <facts, file paths, gotchas the tech lead already knows; list reusable
         scratchpad artifacts (jars, generated reports, probe scripts) by path>
```

## Worker contract

- **Setup** in your worktree: `mise trust --yes && mise run sync`. Tools
  are on PATH through the mise shims. Run anything that needs Java 25
  through `mise run …` or `mise exec -- …`.
- Follow the `red-green` skill. One increment per commit, and every
  commit passes `mise run check`.
- Do **not** push, merge, or edit `docs/PROGRESS.md` or `docs/PROCESS.md`.
  The tech lead owns them.
- **Do** edit `CONTEXT.md` or the interface section of `docs/PLAN.md` in
  the same commit when your increment changes vocabulary or an interface,
  and list it under "Interface changes" in your report.
- Tests that start servers must pick a free ephemeral port, never 25565,
  and must clean up their processes, even on failure. Other workers may
  run servers at the same time.
- Downloads go to the git-ignored cache (`.cache/mscts/`) and are
  hash-verified wherever the source publishes a hash.
- **Shell in worktrees.** The sandbox refuses Bash it cannot verify: `rm -rf`
  with globs, `env -i` in compound commands, heredocs (`cat >> f <<EOF`,
  `python3 - <<EOF`), and `find` on variable paths. Put multi-step
  research in a script file in the scratchpad and run it with
  `sh`/`python3`. Use Edit/Write for code.
- Known tool and type-checker traps are listed in the `red-green` skill.
  Read them first.
- Stay inside the brief. If you are blocked, or the brief is wrong, stop
  and say so in the report rather than widening scope.

## Worker report

End your final message with exactly these sections:

```
## Done
<commit hash + subject, one per line>

## Not done / blocked
<what and why, or "nothing">

## Interface changes
<changes to PLAN.md interfaces or CONTEXT.md terms, or "none">

## Retrospective
For EVERY issue you stumbled on that was not as expected (tooling, docs,
brief, protocol facts, tests, environment), give:
- Expected: …
- Actual: …
- Cost: <time / iterations lost>
- Proposal: <concrete change to the process, a skill, the plan or a goal, or "none">
Finish with the single change that would most have sped you up.
```

## Retrospective log

Newest first. Every retrospective item gets a row.

| Date | Source | Observation | Decision |
| --- | --- | --- | --- |
| 2026-09-25 | worker B (vanilla) | **Offline vanilla calls Mojang services** (authlib discovery, public keys, name lookups). It only fails fast here by accident | **adopt**: opus hardening brief to research `-Dminecraft.api.*` and enforce the invariant "an Instance makes no outbound network calls" |
| 2026-09-25 | worker B | Write/Edit tools turn `\uXXXX` into literal characters | **adopt**: red-green Known traps |
| 2026-09-25 | worker B | The worktree sandbox refuses complex Bash (rm -rf, env -i, heredocs, variable paths) | **adopt**: Worker contract "Shell in worktrees" |
| 2026-09-25 | worker B | Console `op` lower-cases names when services are unreachable | **adopt**: protocol-research Known traps |
| 2026-09-25 | worker B | Flat `generator-settings={}` logs an error and falls back to the classic preset | **defer**: explicit flat JSON only once chunk Comparison proves identity |
| 2026-09-25 | worker B | Spawn was (4.5,-60,-1.5) with seed 0 vs (6.5,-60,7.5) with a random seed | **defer**: Next item, a join-twice determinism check before M4 Masks |
| 2026-09-25 | worker B | argv `"java"` resolves by PATH; the hook's shims pick a version by cwd, and the cwd is the workdir | **adopt**: Adapter contract "argv[0] absolute"; the hardening brief resolves and version-checks Java |
| 2026-09-25 | worker B | Key-set and invariant tests passed an `allow-flight=true` mutation | **adopt**: Adapter contract "golden file from pristine first-run output" |
| 2026-09-25 | worker B | Pin tests cannot start red | **adopt**: red-green "prove it bites with a throwaway mutation" |
| 2026-09-25 | worker B | ty rejects returning `Any`; `type: ignore` is inert | **adopt**: red-green Known traps |
| 2026-09-25 | worker B | ruff SIM300/SIM905 friction | **reject**: trivial |
| 2026-09-25 | worker B | No commit area for `target.py` | **adopt**: added `target` |
| 2026-09-25 | worker B | `.cache/mscts/` is per worktree, so each worker re-downloads | **adopt**: hardening brief resolves the cache via `MSCTS_CACHE` or the main checkout |
| 2026-09-25 | worker B | `prepare` does not clear a reused workdir | **adopt**: Adapter contract "refuse non-empty workdir" |
| 2026-09-25 | worker B | Scratchpad artifacts saved a lot of time | **adopt**: brief template lists them; **defer** a committed `scripts/` research harness |
| 2026-09-25 | lead | The "unit = no processes" rule blocks cheap, hermetic runner tests against a fake server | **adopt**: unit tier is hermetic (no external network, Java or Candidate); localhost helpers allowed |
| 2026-09-25 | lead (integration) | Worktrees share one git stash stack; the red-green skill told workers to `git stash` | **adopt**: the skill now says `git reset --hard HEAD` in your own worktree, never stash |
| 2026-09-25 | lead | Pumpkin ignores `--version` and boots a server in the cwd, writing world/config files | **adopt**: recorded in the research note; never run a Candidate binary outside a scratch workdir |
| 2026-09-25 | worker A (codec) | Increment 1 (VarInt errors) was already implemented, so it only needed tests | **reject**: harmless; pinning existing behaviour with tests is valid |
| 2026-09-25 | worker A (codec) | `String` max `n` ≤ 32767 is not enforced by the primitive; callers pass `max_length` | **adopt**: packet schemas must reject a String field declared with max > 32767 (added to the Codec brief) |
| 2026-09-25 | worker A (codec) | String's byte-length ≤ 3n check is only reachable on the declared prefix; frame-length value > 2097151 is unreachable in 3 bytes | **reject**: documented in tests and code; no process change |

## Process changelog

| Date | Change | Why |
| --- | --- | --- |
| 2026-09-25 | Adopted the tech-lead/worker model with mandatory retrospectives | User direction: the lead steers, workers execute, and the process optimises itself |
