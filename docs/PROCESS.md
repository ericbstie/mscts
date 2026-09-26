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
Base: <main commit the brief was written against>
Context: <facts, file paths, gotchas the tech lead already knows; list reusable
         scratchpad artifacts (jars, generated reports, probe scripts) by path>
```

## Audit checklist

Every audit brief checks at least these, and adds items as reviews find
new classes of defect:

- **Strict at the boundaries.** Every Reader/Writer and wire type raises
  on out-of-range or malformed input, and has a boundary test on each
  side. Worker C found `Writer.var_int` silently wrapping out-of-range
  values.
- **No silent defaults.** Invariants live in one named table, config is
  complete and golden-file tested, and nothing depends on a server or
  host default.
- **Tests bite.** A throwaway mutation of each critical branch turns some
  test red.
- **Cleanup.** Processes, sockets and temp dirs are released on success,
  error, timeout and cancellation.
- **No drift.** The code matches the PLAN interfaces, CONTEXT vocabulary
  and ADRs, or the docs were updated in the same commit.

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
- Downloads go to the shared cache (`mscts.cache.cache_dir()`, outside
  every checkout) and are hash-verified wherever the source publishes a
  hash.
- **Shell in worktrees.** The sandbox refuses Bash it cannot verify. That
  includes `rm -rf` with globs, `env -i` in compound commands, heredocs
  (`cat >> f <<EOF`, `python3 - <<EOF`) mixed with other commands, `find`
  or `sed` on `$VAR` paths, variables in command position, process
  substitution `<(…)`, and `strace … python3 -c`.
  **Default to this:** write any multi-step or scripted shell work to a
  file in the scratchpad (literal absolute paths, no variables), and run
  it as one plain command (`sh /abs/path.sh`, `python3 /abs/path.py`).
  Use Edit/Write for code. `git commit -F - <<'EOF'` on its own works.
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
| 2026-09-26 | worker E (vanilla) | Java version is read from the runtime image's `release` file in `prepare` (hermetic), not by running java in `provision` | **adopt** the deviation; the SessionStart hook now exports `MSCTS_JAVA`, because the mise shims on PATH are refused as non-runtime launchers |
| 2026-09-26 | worker E | authlib discovery property is a URL; log4j is a second outbound path (OS resolver) | **adopt**: `NO_NETWORK` argv table; **defer** a reference test running the Instance under strace and asserting loopback-only connects (after the runner) |
| 2026-09-26 | worker E | `git checkout <file>` to undo a mutation wiped uncommitted work | **adopt**: red-green Known traps "mutate only after committing" |
| 2026-09-26 | worker E | More refused shell forms (the **third** worker to hit this) | **adopt**: Worker contract now makes script files in the scratchpad the default, not a workaround |
| 2026-09-26 | worker E | S603 flags every subprocess call; tests got a per-file ignore | **adopt** for tests (justified); the S603 policy for `src/runner.py` is settled at D's integration |
| 2026-09-26 | worker E | ty rejects returning an `re.Match` group (`Any`) | **adopt**: Known trap extended ("wrap in `str()`") |
| 2026-09-26 | worker E | The launch env passes the harness PATH; timezone, IPv6 and JVM ergonomics come from the host | **adopt**: fixed PATH, `-Duser.timezone=UTC`, `-Djava.net.preferIPv4Stack=true` go in a small vanilla brief; **defer** CPU/GC/memory budgets to an M7 fairness ADR (they must apply to Reference and Candidate equally, so they belong in the runner, not one Adapter) |
| 2026-09-26 | worker E | Stale `.cache/mscts/` in the Worker contract | **adopt**: fixed |
| 2026-09-26 | worker E | Spawn position differs on every fresh run with seed 0, so the join-twice check is moot | **adopt**: Next item replaced with "pin spawn (spawn radius) or Mask `player_position`" |
| 2026-09-26 | workers B, E | A committed research harness (launch a LaunchPlan, optionally under strace, then probe) would have saved the most time. Two workers asked for it | **adopt**: a sonnet brief for `scripts/` once the runner and Bot land |
| 2026-09-25 | worker C (codec) | The worktree guard refuses complex Bash (a repeat of B's finding; C started before that fix landed) | **adopt** (already): Worker contract "Shell in worktrees"; watch for a third occurrence |
| 2026-09-25 | worker C | ty cannot index an `isinstance`-narrowed JSON dict | **adopt**: red-green Known traps recipe |
| 2026-09-25 | worker C | `Writer.var_int`/`var_long` masked out-of-range values; the done-criteria tested only wiki samples | **adopt**: Audit checklist "strict at the boundaries" |
| 2026-09-25 | worker C | The data generator must run outside the repo with mise's Java 25 path; its output is deterministic | **adopt**: protocol-research command, plus a diff-verified regen |
| 2026-09-25 | worker C | `action=raw` can race with wiki edits | **adopt**: fetch by `oldid` in protocol-research |
| 2026-09-25 | worker C | ADR-0003 named the data path `protocol/data/` | **adopt**: corrected to `src/mscts/codec/data/` |
| 2026-09-25 | worker C | Brief increment 4 became 7 commits | **reject**: splitting to one failing test is by design; briefs stay at milestone grain |
| 2026-09-25 | worker C | Main moved 20 commits during the brief | **adopt**: brief template has a `Base:` line; integration is the lead's job |
| 2026-09-25 | worker C | `Packet.fields` is a mutable dict inside a frozen dataclass | **defer**: decide with the Transcript/Comparison design (M2); added to PLAN open questions |
| 2026-09-25 | worker C | Decoded values are plain int/str/bool/bytes/UUID/list/dict/None | **adopt**: confirmed as the codec value model |
| 2026-09-25 | worker C | ADR-0003's reference-tier layout verification needs Connection | **defer**: part of the Connection + `Bot.status` brief |
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
