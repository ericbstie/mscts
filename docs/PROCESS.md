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

## Working with the maintainer

The maintainer (the user) sets direction. The tech lead turns it into
ADRs and briefs. What the maintainer has asked for:

- **Decisions are theirs when they shape the product.** Ask with
  concrete options and a recommended one first (the AskUserQuestion
  tool), then record the answer as an ADR or a PROGRESS entry in the same
  turn. Never let a decision live only in chat.
- **Explain before asking.** When the maintainer says they don't follow,
  explain the mechanism plainly (see the TLS-proxy discussion behind
  ADR-0008) before offering options again.
- **Status reports:** a short bullet summary of what was done, the
  architecture, process changes from worker feedback, what's left, and the
  decisions that need them.
- **Product intent** (ADR-0006–0008):
  - surface every difference from vanilla, with no excuses and no hidden
    randomness;
  - an elegant, honest developer experience;
  - installs are never hidden inside runs;
  - Adapters are easy for third parties to write and verify.
- **Helper agent.** The maintainer also runs a non-Claude agent that
  takes GitHub issues labelled `helper-ready`. The lead may delegate a
  small, independent Next item there as a self-contained issue (the
  brief's rules, a PR as hand-back) and marks it delegated in PROGRESS.
  Claude remains the primary worker; the process is not shaped around
  the helper. Its PRs get the same review and rebase-with-check
  integration, and the surprises in its PR description are logged as a
  retrospective.
- **Autonomy:** within those decisions, the lead steers without asking,
  including batches, audits, refactors and process changes, and keeps
  the maintainer informed.

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
Increments (in order, one commit each; say whether a new dataclass field may default;
              a suggested signature keeps ≤ 5 parameters (PLR0913) or says "shape it")
              <numbered list; name the target module explicitly,
              e.g. `src/mscts/bot.py`, not just an area label>
Interfaces: <PLAN.md section(s) to implement exactly; allowed deviations>
Out of scope: <what not to touch>
Adapter/Candidate tests assert observable outcomes (chunk contents, spawn), never
              a wire field a Candidate may legitimately get wrong: that is a Divergence
              for the Comparison to report, not a harness assertion.
Done when: <observable condition, e.g. `mise run check` green + named tests exist;
           timings are measured on a committed tree, with `--durations` of the touched
           tests and the load average>
Base: <main commit the brief was written against; the worker first runs
      `git merge --ff-only main` in its worktree>
Context: <facts, file paths, gotchas the tech lead already knows; reusable scratchpad
         artifacts (jars, generated reports, probe scripts) by path; names a parallel
         brief is introducing that this one must not reuse (check CONTEXT.md);
         the migration rule if this brief changes anything persisted (cache, files)>
         Scratch files go in `<scratchpad>/<worker letter>/` (the scratchpad is shared).
         ALWAYS include verbatim: "One plain command per Bash call; multi-step work goes in
         a script in the scratchpad; commit only with `mise run commit -- -F /abs/msg.txt`
         (it runs the check and commits only if green); never `git stash`.""
End with: the Worker report exactly as specified in docs/PROCESS.md, including a thorough
          Retrospective; state your worktree path and branch name.
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
- **Identity by ownership.** A check that a server is *the* server proves
  it by ownership (process, socket), never by the server's own answer.
- **No Mask hides gameplay.** Every Mask's reason shows the field has no
  player-observable meaning (ADR-0006).
- **Candidate output never crashes the harness.** Malformed or
  undecodable Candidate output is recorded and becomes a `mismatch`,
  never an `error` (which the compliance score excludes).
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
- On an unrelated red (a test you did not touch), first run
  `git merge --ff-only main`: the lead may have fixed it already.
- Tests and tools that run git must drop every `GIT_*` env var. Under
  `git rebase -x`, `GIT_DIR` points at the real repository.
- Git commands against the main checkout are refused from a worktree.
  Read its files directly instead.
- Commit only with `mise run commit -- -F /abs/msg.txt`: it runs the
  check unpiped and commits only on exit 0. Never pipe `mise run check`
  into a commit chain (the pipe's status is the last command's).
- **Leak guard for process-starting tests.** Tag each spawned process's
  environment with a per-test token. At teardown, scan `/proc` for the
  token, SIGKILL any survivor, and fail the test (see
  `tests/runner/conftest.py`). Do not verify with `pgrep -af`: it matches
  the harness's own shell wrapper. In this container PID 1 reaps orphans
  only after 1–3 s, and `pid_max` is 32768. To check by hand (e.g. before
  ending a session), `python3 scripts/strays.py <pattern>` reads `/proc`
  directly and excludes itself and its whole ancestor chain, so it never
  matches its own invocation or the wrapper that ran it; it exits
  non-zero if it finds anything.
- Never write a brief stand-in that contradicts an ADR. If the real
  thing is not built yet, the worker builds the smallest faithful version
  or stops and reports. (Lead lesson from worker D: a TCP-connect
  "readiness" stand-in cost 25 minutes.)
- Downloads go to the shared cache (`mscts.cache.cache_dir()`, outside
  every checkout) and are hash-verified wherever the source publishes a
  hash.
- **Shell in worktrees.** The sandbox refuses any Bash it cannot verify,
  and it is inconsistent at the edges (five workers have hit it). The
  rule that always works: **one plain command per Bash call**. Do not
  chain with `&&`, `;` or `|` when the command also has a heredoc, a
  `$VAR`, `$(…)` or `python -c`. Use literal absolute paths, not
  variables. For anything longer, Write a script file into the
  scratchpad and run it as a single plain command (`sh /abs/x.sh`,
  `python3 /abs/x.py`). Use Edit/Write for code.
- **Run tiers through mise**: `mise run test:reference -- <pytest args>`.
  A plain `uv run pytest` uses the host toolchain (Java 21 here), which
  the Reference Adapter correctly refuses unless `MSCTS_JAVA` is set.
- Known tool and type-checker traps are listed in the `red-green` skill.
  Read them first.
- **Commit early.** An interrupted agent (API rate limit, container
  restart) loses a worktree that has no commits. Keep research artifacts
  in your scratch dir, where the next worker can reuse them.
- Before committing a change to a `Protocol`, grep main for every
  implementer and caller again: a parallel brief may have added one.
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
| 2026-09-26 | lead (incident) | A second API rate limit killed Z (audit, skeleton only), Y (had finished) and AA (after increment 1). Y and AA's first increment were integrated; Z's skeleton was dropped | **adopt**: Z and AA's remaining increments are re-briefed next session; the "commit early" rule saved AA's first increment |
| 2026-09-26 | worker Y (research harness) | Scripts reusing sibling scripts needed a load-by-path pattern (15 min) | **adopt**: red-green Known trap |
| 2026-09-26 | worker Y | Ctrl-C under `asyncio.run()` arrives as task cancellation | **adopt**: red-green Known trap |
| 2026-09-26 | worker Y | PLR0913 keeps recurring | **adopt**: red-green hint, bundle co-passed values into a small dataclass |
| 2026-09-26 | worker Y | `join.py` also shows vanilla vs Pumpkin differences in `dimension_names` order and `enforces_secure_chat` (true on Pumpkin) | **adopt**: added to the known Pumpkin Divergences for the first Report |
| 2026-09-26 | worker W (Run over Endpoints) | A timing baseline taken while editing measures a moving tree, and main moved mid-measurement | **adopt**: brief template, "measure timings on a committed tree and do not edit during a run"; **defer** a snapshot-based `scripts/time_tier.py` |
| 2026-09-26 | worker W | Load from parallel workers (loadavg 3–4 on 4 CPUs) moved tier totals by more than the saving | **adopt**: G5 claims report the touched tests' `--durations` and the load average alongside the tier total |
| 2026-09-26 | worker W | The reference tier is 79–83 s after the fix: under G5, with a thin margin. The join keep-alive test idles about 30 s | **adopt**: Next item, run the reference tier with `-n 2 --dist loadgroup`, the keep-alive test in its own `xdist_group` |
| 2026-09-26 | worker W | "Commit only with `mise run commit`" landed mid-brief and W learned it only at rebase | **adopt**: the lead messages in-flight workers whenever the Worker contract changes |
| 2026-09-26 | worker W | Two-Bot tests needed a tolerant `_mute` fake handler | **defer**: move it to `tests/net/fakes.py` when a second test needs it |
| 2026-09-26 | worker W | A re-indent by string replacement mangled a file | **reject** (no change): use Edit for structural changes |
| 2026-09-26 | worker X (tooling) | `mise run commit`, `strays.py --token/--cwd`, `mutate.py --batch` with untracked files landed; PLR0913 forced a cleaner shape twice | **adopt**: the brief template's verbatim line and the Worker contract now require `mise run commit`; the helper split is the pattern for synthetic-/proc tests |
| 2026-09-26 | helper (Astra, PR #5 javap) | Its sandbox's PID namespace broke the process tests, so it could not run the full check; a sonnet review found the version JSON was trusted without its manifest sha1 | **adopt**: the lead runs the full check and a live smoke test on every helper PR, and fixes small findings in a commit on top of the PR branch (never rewriting it), then rebase-merges. Helper issues spell out the trust chain to verify |
| 2026-09-26 | worker V (wire-only) | A committed javap with DFU and Gson on the classpath would have saved a third of the brief | **adopt**: delegated as issue #6 (extends #5) |
| 2026-09-26 | worker V | `ServerStatus.CODEC` uses `lenientOptionalFieldOf`; only the absent case meets the evidence standard | **reject** (no change): the evidence standard held; protocol-research note added |
| 2026-09-26 | worker V | Canonical values are compared before Masks, so a re-spelling inside a field that also has an observable or masked difference is not reported separately | **accept**: a deliberate, documented limit (PLAN) |
| 2026-09-26 | worker V | Tag lists decode last-write-wins: only a stable sort is sound | **adopt**: protocol-research Known trap |
| 2026-09-26 | worker V | Whether vanilla's `update_tags` order is stable across runs is unverified; if not, the join Self-check fails its exact `match` | **adopt**: the join Scenario brief (Next 7) checks it first |
| 2026-09-26 | worker V | A reordered `update_tags` yields one wire-only Divergence per shifted leaf | **defer**: the Report brief (Next 4) decides grouping |
| 2026-09-26 | worker V | Two more shell refusals (`cd … &&` heredoc; a plain `cat >> f <<EOF`) | **adopt**: red-green Known trap, `uv run --directory` / `mise run --cd` and Write/Edit |
| 2026-09-26 | worker U (Pumpkin world) | `is_flat=false` and `sea_level` 63 are hard-coded in Pumpkin; the brief suggested asserting `is_flat` in an Adapter test | **adopt**: brief template, Adapter/Candidate tests assert observable outcomes, never a wire field a Candidate may get wrong; both are known Pumpkin Divergences for the join Report (research note) |
| 2026-09-26 | worker U | Committed once through `mise run check \| tail && git commit` (the check was green on re-run). The **second** slip of this rule (H before) | **adopt**: repeated, so make it impossible: Next tooling item `mise run commit -- -F <msg>` (check, then commit only on exit 0) |
| 2026-09-26 | worker U | A long `python3 - <<EOF` was refused by the sandbox, shorter ones passed | **adopt**: Worker contract, heredocs and inline scripts always go into a scratch file, no exceptions |
| 2026-09-26 | worker U | Live tests can read `Packet.payload` without a schema | **adopt**: protocol-research line |
| 2026-09-26 | worker U | Pinning the NBT writer against a file the Reference wrote was the strongest test | **adopt**: red-green hint |
| 2026-09-26 | worker U | ty rejects `cast` to a disjoint type | **adopt**: red-green Known trap |
| 2026-09-26 | worker U | `strays.py server.jar` matched another worker's live vanilla | **defer**: Next tooling, `strays.py --token/--cwd` to scope the check |
| 2026-09-26 | worker U | A committed `scripts/research/boot.py` (boot an Adapter's Instance, join, dump packets and chunks, keep the workdir) would have saved the most | **adopt**: Next item 6 takes U's scratch `U/boot.py`, `U/nbtdump.py`, `U/chunk.py` as its starting point |
| 2026-09-26 | worker T (install) | R landed two more Adapter implementers and callers mid-brief | **adopt**: the lead messaged T when R landed; Worker contract "grep for implementers again before committing a Protocol change" |
| 2026-09-26 | worker T | `test_repeat`'s stress test flaked: it read `/proc` before the children exec'd (a known trap, missed in Q's test) | **adopt**: fixed by the lead (poll until tagged), 20/20 under stress |
| 2026-09-26 | worker T | The brief suggested an 8-parameter signature (PLR0913 allows 5) | **adopt**: brief template, suggested signatures keep ≤ 5 parameters or say "shape it" |
| 2026-09-26 | worker T | A clean one-line fail-fast needed a collection hook that xdist workers skip | **reject** (no change): hook plus per-test fallback, documented |
| 2026-09-26 | worker T | ruff format joined a split string, then ISC004 fired inside `[...]` | **adopt**: red-green Known trap |
| 2026-09-26 | worker T | `provision` removed from the Adapter Protocol; a third-party Adapter is `name`, `binary`, `check`, `prepare` | **accept**: the smallest contract (G6); installs live in `install.py` |
| 2026-09-26 | lead (incident) | An API rate limit killed T, U and V at once. T and U were resumed by message with their worktrees intact; V had no commits, so its worktree was auto-removed and it was relaunched, reusing its scratch research | **adopt**: Worker contract "commit early: a worktree with no commits does not survive an interrupted agent; keep research in your scratch dir"; the lead resumes interrupted workers by message when their worktree survives |
| 2026-09-26 | lead (integration of R) | R's test fakes implemented `Adapter` without S's new `binary`/`check` members: ty red only after the rebase | **adopt**: when one brief changes a Protocol, the lead names every in-flight implementer in the other briefs, and messages running workers when it lands (done for T) |
| 2026-09-26 | lead (incident) | Intermittent unit-tier red on main: S's parametrize ids embedded fake-jar bytes with wall-clock zip mtimes, so xdist workers collected different tests. Q's 25 stress runs predate S | **adopt**: fixed (bd6d44f); red-green Known trap "deterministic parametrize ids"; in-flight workers told |
| 2026-09-26 | worker R (M2) | The reference tier went 83 s → 91.4 s (G5 red): the Self-check boots two more Instances | **adopt**: Next item 2a, a Run over existing Endpoints so the Self-check reuses the session Reference |
| 2026-09-26 | worker R | `mutate.py --batch` ignores untracked test files (**second** report, after S) | **adopt**: repeated, so fix the tool: Next item, batch mode includes untracked non-ignored files |
| 2026-09-26 | worker R | The "Registry" rename arrived after four commits; fixups needed a scripted autosquash and filter-branch | **adopt**: the template now names taken terms (S's row); red-green Known trap for fixup + autosquash without an editor |
| 2026-09-26 | worker R | The run fakes' `serve` overwrites `__cause__` | **adopt**: red-green Known trap |
| 2026-09-26 | worker R | `tests/run/status_fake.py` (a subprocess status fake that passes readiness and ownership) was needed | **reject** (no change): it is reusable; later briefs will be pointed at it |
| 2026-09-26 | worker R | Tests isolate `SCENARIOS` through the private `_REGISTERED` | **defer**: a public test-support context manager when a second test module needs it |
| 2026-09-26 | worker R | A `failed` Divergence has `bot=""`: the exceptions do not carry the Bot (a G3 gap) | **defer**: Next item, Bot errors carry the Bot name |
| 2026-09-26 | worker R | Went to about 1666 lines, over the budget, to finish a small increment 5 | **accept** once: the last increment was small and fully tested; the budget stands |
| 2026-09-26 | worker S (install) | "Registry" (the server list, CONTEXT) was about to be reused by R for the Scenario set | **adopt**: R told to use `SCENARIOS` / "registered Scenarios"; the brief template's Context names terms a parallel brief introduces |
| 2026-09-26 | worker S | The scratchpad is shared; another worker overwrote S's commit-message file | **adopt**: brief template gives each worker `<scratchpad>/<letter>/` |
| 2026-09-26 | worker S | "+ vanilla if it shares the path" grew increment 2 to about 800 lines, and the prompt increment was dropped | **adopt**: optional co-changes count as their own increment in the line budget; the prompt is Next item 3b |
| 2026-09-26 | worker S | A legacy cache (vanilla jar, no SOURCE.json) appeared mid-brief and broke the strict `installed()` | **adopt**: briefs that change a persisted format state the migration rule up front. S's rule (record only on a Registry hash match) is accepted |
| 2026-09-26 | worker S | A new Protocol member breaks every implementer under ty | **adopt**: red-green Known trap |
| 2026-09-26 | worker S | RUF043, a `[[` `match=` FutureWarning, ty `@override`, `**dict` into a dataclass, argparse `set_defaults` Any | **adopt**: red-green Known traps |
| 2026-09-26 | worker S | `mutate.py` batch mode ignores untracked test files | **adopt**: red-green Known trap (`git add` first) |
| 2026-09-26 | lead (review of S) | `provision` still downloads when nothing is installed, and `installed()` silently writes SOURCE.json for a legacy cache: both break ADR-0008's "nothing installs without saying so" | **adopt**: Next item 3b, the honest prompt; Runs use `installed()` + prompt, never a silent download; the legacy migration says what it recorded |
| 2026-09-26 | worker Q (xdist) | `free_endpoint`, the leak guard and `strays.py` were already safe under xdist; checking cost 15 min | **reject** (no change): the brief pointed at the right files; verifying beat assuming |
| 2026-09-26 | worker Q | `ty` cannot resolve `tests/support/leak_guard.py` from `scripts/`, so `repeat.py` carries a second copy of the pattern | **defer**: promote it to a module `scripts/` can import when a third copy is needed |
| 2026-09-26 | worker Q | Failing ids come from the `-ra` summary lines on stdout | **reject**: simple and sufficient |
| 2026-09-26 | lead | Unit tier under xdist: 4.3–5.6 s (was 11.5 s); 20 xdist + 5 serial runs under CPU stress, 0 failures | **adopt**: G5 restored; the temporary integration retry (`\|\| mise run check`) is removed. A red check on integration is now a real failure, re-proved with `scripts/repeat.py` |
| 2026-09-26 | worker P (join) | The brief was too big: 6 large increments, 29 commits, and the context compacted mid-brief | **adopt**: briefs stay at 3–6 increments **and** roughly 1500 changed lines. Split protocol fixes from features |
| 2026-09-26 | worker P | Nearly every join fact needed client-side javap; P rebuilt the tooling (`fetch_client.py`, `javap_classes.py`) | **adopt**: Next item, a committed `scripts/research/javap.py <client\|server> <Class>…` that fetches and caches both jars |
| 2026-09-26 | worker P | `/proc`-scanning tests raced the helper's exec | **adopt**: fixed (P's commit); Known trap "wait for the helper to exec; ignore processes you did not start" |
| 2026-09-26 | worker P | Threaded fakes acted before the client had connected (a flaky MD2 test) | **adopt**: Known trap, fakes wait for a "client connected" cue; poll via an `asyncio.Event` set by the fake; split long fake handlers early (PLR0915) |
| 2026-09-26 | worker P | A public name landed without its PLAN entry | **defer**: Next item, a check that every new public name in `src/` appears in PLAN.md |
| 2026-09-26 | worker P | Setting work aside without stash needed a save/restore script | **defer**: a `scripts/` split helper |
| 2026-09-26 | worker P | `update_tags` order comes from a server HashMap | **adopt**: Canonicalization item for the join Scenario's Self-check |
| 2026-09-26 | worker P | The Bot does not yet send brand/`client_information`/`player_loaded` as the vanilla client does | **defer**: Next item (Bot fidelity) |
| 2026-09-26 | worker P | The sandbox refused compound commands again (**sixth** report) | **adopt**: the brief template's Context now repeats the one-command rule verbatim |
| 2026-09-26 | lead | The unit tier is 11.5 s after the join landed, breaching G5 | **adopt**: Next item 1, pytest-xdist plus the flake hunt |
| 2026-09-26 | lead (incident) | A worker N test ran `git init/config/commit` in a tmp dir during `git rebase -x`. The inherited `GIT_DIR` pointed it at the real repo: it wrote `user.name=Test` and `core.bare=true` into the shared config and committed onto the rebase. Three of worker P's in-flight commits were authored "Test". The lead's own `merge \| tail && worktree remove && branch -D` then hid the merge failure and deleted N's branch (recovered from the reflog) | **adopt**: (1) every test and tool that runs git scrubs `GIT_*` env vars (fixed in `tests/tooling/test_mutate.py` and `scripts/mutate.py`, with a pin test); (2) the lead never pipes a git command in an `&&` chain and checks `$?` explicitly (tech-lead skill); (3) after every integration, check that `git config --local --list` has no `user.*` and `core.bare=false` |
| 2026-09-26 | lead | Integration re-checks retry `mise run check` once (`\|\| mise run check`) while other workers load the machine | **temporary**: it hides flakes, so each retry that was needed is logged. Remove it once the flake hunt is done |
| 2026-09-26 | worker N (mutate) | `uv run` ignores `VIRTUAL_ENV` from an unrelated cwd (use `UV_PROJECT_ENVIRONMENT` + `--no-sync`); the editable `.pth` names the original checkout, so a copy needs `PYTHONPATH=<copy>/src` first; `mkdtemp` already creates its dir | **adopt**: red-green Known traps |
| 2026-09-26 | worker N | New mutate.py exit codes: 0 KILLED, 1 SURVIVED, 2 setup error, 3 INVALID; batch mode baselines once for the whole batch | **adopt**: documented in red-green |
| 2026-09-26 | worker N, M | `test_strays` flaked on other processes' multi-line argvs | **adopt**: fixed on main (91bd6c1) |
| 2026-09-26 | worker M (runner) | The lead's environment fix landed while M fixed the same thing in parallel (a duplicate commit) | **adopt**: after landing a fix for a shared red, the lead messages in-flight workers (done for P); Worker contract: "on an unrelated red, `git merge --ff-only main` before fixing it yourself" |
| 2026-09-26 | worker M | A readiness change nearly shipped a flaky test | **adopt**: red-green rule, run touched readiness/timing/process test files 20× before committing; **defer** a committed `scripts/repeat.py` (M's scratch `l-repeat.py`) |
| 2026-09-26 | worker M | `-k` does not match hyphenated parametrize ids; mutate.py's old false KILLED bit again | **adopt**: fixed by N's exit-code rules; Known trap for `-k` |
| 2026-09-26 | worker M | G5 at its limit (check 9.4–9.8 s) | **adopt**: Next item, pytest-xdist |
| 2026-09-26 | worker M | A required new dataclass field forces every construction site to change at once | **adopt**: brief template, say whether a new field may have a default |
| 2026-09-26 | worker M | No IPv6 in this container; ownership is IPv4-only, and it fails loudly | **adopt**: Adapter contract "Java Candidates bind IPv4 (`preferIPv4Stack`)"; tcp6 support needs a host with IPv6 |
| 2026-09-26 | worker M | The candidate tier runs here with a scratch `MSCTS_CACHE` holding the pinned binary plus `SOURCE.json` | **adopt**: noted for briefs until `mscts adapter install --from` exists |
| 2026-09-26 | worker M | ty: `return frozenset()` infers `frozenset[Unknown]`; `cast("str", x)` for deliberately wrong test types; PTH115 | **adopt**: Known traps |
| 2026-09-26 | worker M | Identity checks must prove ownership, not trust an answer | **adopt**: Audit checklist item |
| 2026-09-26 | worker K (audit) | `scripts/mutate.py` counts any non-zero pytest exit as KILLED, so a mistyped path "bites" (MD6). This weakens every earlier "proven to bite" claim | **adopt**: top-priority tooling fix (verdict needs failed tests, a no-op sanity run, `PYTHONDONTWRITEBYTECODE=1`, a parallel copy-based batch mode) |
| 2026-09-26 | worker K | High findings: H1 readiness accepts any server at the Endpoint; H2 receive time is take time, not arrival; H3 an undecodable Candidate packet is unrecorded and would become `error` (excluded from compliance) | **adopt**: an opus fix batch before M2 wiring. Policy: **a failure caused by Candidate output is `mismatch`, never `error`** |
| 2026-09-26 | worker K | `FrameDecoder.feed` also misdecodes a valid frame after `login_compression` | **adopt**: delete it. New lead default: a lossy API a worker reports is deleted, not deferred |
| 2026-09-26 | worker K | Git on the main checkout is refused from a worktree; audit ids collided with milestone ids; "sound" was nearly claimed before the evidence | **adopt**: Worker contract line; audit ids H#/MD#/L#; audit claims need evidence first |
| 2026-09-26 | workers J, K | `javap -c -p -constants` on the unobfuscated 26.3 jar (`META-INF/versions/26.3/server-26.3.jar`) settled facts the wiki can't | **adopt**: protocol-research recipe; **defer** caching the client jar |
| 2026-09-26 | workers J, K | Subagents received a stale CLAUDE.md (gh issues, `docs/agents/`) from the session's start | **resolved**: the restarted session injects the current CLAUDE.md; on-disk docs win |
| 2026-09-26 | worker J (compare) | Worktree spawned from a stale base | **adopt**: brief template says to run `git merge --ff-only main` first |
| 2026-09-26 | worker J | A heredoc commit message was refused once | **adopt**: default is to Write the message to a scratchpad file, then `git commit -F /abs/msg.txt` |
| 2026-09-26 | worker J | An "optimization" branch (suffix trim) changed results; a mutation survived | **adopt**: red-green rule, prove optimization branches by an exhaustive small-domain check |
| 2026-09-26 | worker J | ty: use a recursive `type _Value = …` alias; aliases must be defined above first use (eager annotations) | **adopt**: Known traps |
| 2026-09-26 | worker J | Deep JSON could make `compare` raise, turning a mismatch into an excluded `error` | **adopt**: Audit checklist item "no Candidate output can make the harness raise" |
| 2026-09-26 | worker J | Declared defaults (missing `players.sample` ≡ `[]`) not canonicalized | **user decision pending** |
| 2026-09-26 | worker H (pumpkin) | Pumpkin cannot honour FLAT or difficulty, so `prepare` refuses every ServerSpec | **user decision pending** (native flat world save vs. per-Scenario spec needs vs. refuse) |
| 2026-09-26 | worker H | The proxy re-signs GitHub hosts with a CA that Python 3.13's strict X.509 rejects, so Candidate provision fails here | **user decision pending**; TLS is never weakened |
| 2026-09-26 | worker H | Pumpkin's offline UUID is `sha256(name)[:16]`, not vanilla's; a bad config value silently loads Pumpkin's full defaults; the Bedrock OIDC fetch runs with Bedrock off | **adopt**: protocol-research traps (Candidates may derive offline UUIDs differently; range-check every value) |
| 2026-09-26 | worker H | `check | grep && git commit` committed through a failing check; a stale `.pyc` survived a same-second restore | **adopt**: never pipe the check into a commit chain; `mutate.py` gets `PYTHONDONTWRITEBYTECODE=1` |
| 2026-09-26 | worker H | Pristine Candidate runs need a network sandbox (`unshare -n` + loopback) | **adopt**: in the research-harness brief, with H's scratch tools |
| 2026-09-26 | lead | One unreproduced unit-tier failure while rebasing H (6/6 clean reruns at low load) | **defer**: flake hunt under CPU stress |
| 2026-09-26 | worker I (tooling) | The session-scoped async fixture pairing (`loop_scope`) is undocumented in the repo and cost 30–40 min | **adopt**: red-green Known trap |
| 2026-09-26 | worker I | importlib mode already synthesizes `tests.*` packages; `pythonpath` is for plain helpers | **adopt**: Known trap |
| 2026-09-26 | worker I | Script lint friction: EXE001, D301, PYI025, S105 on names | **adopt**: Known trap |
| 2026-09-26 | worker I | The two-boot runner test can exceed the global 120 s timeout | **adopt**: the lead added `@pytest.mark.timeout(300)` |
| 2026-09-26 | worker I | Habitual `git stash` for a throwaway experiment (refused by the sandbox) | **adopt**: the skill now names this case |
| 2026-09-26 | worker I | Hermetic tests for `strays.py` caught two real bugs early | **reject** (no change): red-green working as intended |
| 2026-09-26 | lead | Audit cadence reached (4 batches). The foundation (codec, net, bot, transcript, runner) is about to carry join and Comparison | **adopt**: opus audit brief K, read-only, report in `docs/audits/` |
| 2026-09-26 | worker G (regen/env) | A plain `uv run pytest` picks up the host Java 21 | **adopt**: Worker contract "run tiers through mise" |
| 2026-09-26 | worker G | The noqa + nosec same-line syntax took trial and error | **adopt**: red-green Known trap |
| 2026-09-26 | worker G | A probe retry catching only `OSError` missed `EOFError` | **adopt**: protocol-research trap |
| 2026-09-26 | worker G | Judgment call: `LAUNCH_ENV = {"PATH": "/usr/bin:/bin"}` rather than `{}` | **accept**: conservative and verified live |
| 2026-09-26 | lead (review of G) | A per-file ruff ignore rode along in a feature commit rather than its own `tooling:` commit | **accept** this once (narrow, justified); the rule stands |
| 2026-09-26 | worker F (net/bot) | Lost uncommitted work undoing a mutation with `git checkout`. This is the **second** occurrence (E); F started before the trap was written | **adopt**: a committed `scripts/mutate.py` (single-match replace, run pytest under timeout, restore from backup) in the harness brief; red-green will point to it |
| 2026-09-26 | worker F | ASYNC109 forbids `timeout` parameters | **adopt**: convention `timeout_s`, in Known traps |
| 2026-09-26 | worker F | PLR0913 on 6 parameters; a pre-emptive `noqa` | **adopt**: Known traps (≤5 params, never pre-emptive noqa) |
| 2026-09-26 | worker F | The Bash guard is inconsistent (**fifth** report) | **adopt**: the Worker contract rule is now "one plain command per Bash call", with scripts for everything else |
| 2026-09-26 | worker F | A leaked socket failed a later test | **adopt**: Known trap (closing context managers in tests) |
| 2026-09-26 | worker F | A global monkeypatch of an asyncio class hung the suite | **adopt**: Known trap; pytest-timeout goes in the next tooling brief |
| 2026-09-26 | worker F | "`net`: status_probe" was impossible without a circular import | **adopt**: brief template names modules explicitly; `transcript` added to the areas |
| 2026-09-26 | worker F | Recording when a frame is *taken* (not read) keeps Transcripts independent of TCP segmentation, but untaken trailing packets are absent | **adopt** as the policy; added to PLAN open questions with the background reader and windows |
| 2026-09-26 | worker F | `FrameDecoder.feed` still loses frames before a corrupt one; a non-zero data-length below the threshold is accepted | **defer**: join brief (fix or remove `feed`; verify vanilla's rule) |
| 2026-09-26 | worker F | TaskGroup wraps exceptions; frozen clock needed to pin a bound | **reject**: handled in code |
| 2026-09-26 | worker D (runner) | **The lead's brief** prescribed a TCP-connect stand-in probe. Vanilla accepts TCP before its world exists and loses a `stop` read then | **adopt**: ADR-0004 consequence, protocol-research trap, and a Worker contract rule: never brief a stand-in that contradicts an ADR |
| 2026-09-26 | worker D | A loose mutation `sed` hit two lines and hung pytest | **adopt**: red-green trap (line-addressed, single match, `timeout 60`) |
| 2026-09-26 | worker D | Process-starting tests leak by design when red or mutated | **adopt**: Worker contract leak-guard pattern (per-test env token + `/proc` sweep) |
| 2026-09-26 | worker D | PID 1 reaps lazily (1–3 s); `pid_max` 32768 | **adopt**: Worker contract note |
| 2026-09-26 | worker D | More refused shell forms (`$(git …)`, `python -c` in compound commands). **Fourth** occurrence | **adopt**: list extended. If a fifth worker reports it, make a tiny `scripts/` runner the only allowed pattern |
| 2026-09-26 | worker D | `pgrep -af` matches the harness wrapper | **adopt**: `scripts/strays.py` goes in the research-harness brief |
| 2026-09-26 | worker D | The stop outcome has no typed home (logged only) | **defer**: a typed stop record for M7's `instance.stop` Measurement |
| 2026-09-26 | worker D | Unit tier went 0.4 s → 4.1 s (real stop timeouts) | **accept**: G5 holds; watch it, pytest-xdist if it passes about 7 s |
| 2026-09-26 | worker D | A vanilla boot takes about 10 s, so G5 allows about 8 boots in the reference tier | **adopt**: Next item, a session-scoped Reference Instance fixture; **defer** AppCDS (it would distort the G4 startup Measurement) |
| 2026-09-26 | worker D | Lint/type friction: PLR0913, PT012, ty possibly-unresolved, ASYNC110 | **adopt**: red-green trap with the passing shapes |
| 2026-09-26 | worker D | Test helpers cannot be imported under importlib mode | **adopt**: `pythonpath = ["tests"]` + a `tests/support/` package, in the next tooling brief |
| 2026-09-26 | worker D | A SIGKILLed harness orphans server groups | **defer**: Next item, a parent-death guard or a pgid file swept at session start |
| 2026-09-26 | worker D | Through `free_port`'s race, a probe can reach another worker's vanilla, which also answers 777 | **adopt**: Next item, a distinct loopback host per Instance (`ServerSpec.host` in 127/8). This is a Verdict-integrity risk under parallel workers |
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
| 2026-09-26 | Commits go through `mise run commit` (check, then commit only if green) | The piped-check slip happened twice |
| 2026-09-26 | Independent Next items may be delegated to the maintainer's helper agent via `helper-ready` GitHub issues | Maintainer: an optional helping hand; Claude stays primary |
| 2026-09-26 | ADR-0008: explicit idempotent installs (`mscts adapter install`, `--from`), an honest prompt, a checksum-pinned registry, Adapter authoring guide + conformance kit, DX goal G6 | User direction: an elegant, honest DX; installs never hidden in test runs |
| 2026-09-26 | ADR-0007: wire-only Divergences are reported separately and excluded from scores; the Pumpkin Adapter writes native world saves | User decisions |
| 2026-09-26 | ADR-0006: catalogue of differences; exact/tick-exact/statistical Scenarios; Masks only for non-gameplay ids; commands-only Fixtures | User direction: surface every difference (randomness, redstone, glitches) without hiding any |
| 2026-09-25 | Adopted the tech-lead/worker model with mandatory retrospectives | User direction: the lead steers, workers execute, and the process optimises itself |
