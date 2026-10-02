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
- Owns the queue (GitHub issues labelled `ready`, ADR-0009),
  `docs/PROGRESS.md`, `docs/PLAN.md`, the ADRs, this file, and the skills.
- Writes spec issues with the maintainer, briefs workers on them, chooses
  the model, and spawns workers.
- Reviews each worker's PR against its issue and merges it with a rebase,
  so every commit on `main` passes `mise run check`.
- Reads every retrospective and decides what to change.
- Sends work to refactoring or auditing when retrospectives or reviews
  show drift.
- Writes product code only for trivial integration fixes. Anything more
  goes in a brief.

**Worker (a subagent).** Owns exactly one issue and its PR, following the
`red-green` skill, in an isolated git worktree. It commits each increment
green, pushes its `issue-<n>-<slug>` branch, opens the PR, and ends with
the [report](#worker-report) to the tech lead.

## Working with the maintainer

The maintainer (the user) sets direction. The tech lead turns it into
ADRs and briefs. What the maintainer has asked for:

- **Decisions are theirs when they shape the product.** Ask with
  concrete options and a recommended one first (the AskUserQuestion
  tool), then record the answer as an ADR or a PROGRESS entry in the same
  turn. Never let a decision live only in chat.
- **One question at a time.** When pinning down an interface or a
  wording, ask a single question, wait for the answer, then ask the next.
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
  small, independent spec issue there by adding that label.
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

1. **Plan a batch.** Choose 1–3 `ready` issues whose "Owns" lists
   (files, modules and doc sections) are disjoint, so they can run in
   parallel without conflicts. Skip any labelled `needs-decision`.
2. **Brief and spawn** each one in the background with worktree
   isolation, using the [template](#brief-template). The issue is the
   spec; the brief adds only what the lead knows beyond it.
3. **Integrate** each PR as it finishes:
   - Review the diff against the issue: the Docs delta applied verbatim,
     the Interface exact, the Acceptance tests present and failing
     without the code. Check that no lint, type or security rule was
     loosened, and that the vocabulary matches `CONTEXT.md`.
   - Rebase onto `main` with every commit re-checked:
     `git rebase main -x "mise run check"`.
   - Merge the PR with a rebase (never a squash), which closes the issue.
   - Read the issue's comments: a scope change the worker recorded there
     may need a follow-up issue.
   - If it was an `enabler` issue, add `ready` to every `test` issue whose
     Needs have now all landed.
4. **Retrospective intake.** Log every item in the
   [retrospective log](#retrospective-log) and decide one of:
   - **adopt**: change the skill, PLAN, PROCESS or goal now, in a
     `docs:` or `tooling:` commit;
   - **defer**: open a spec issue for it;
   - **reject**: record why.
5. **Update `docs/PROGRESS.md`** (Now, Log) and push.
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

Issue: #<n> (the spec: Docs delta, Interface, Acceptance tests, Owns). Read it
       and its comments first. Branch: issue-<n>-<slug>.
Goal: <one sentence, in CONTEXT.md vocabulary>
Increments (in order, one commit each; say whether a new dataclass field may default;
              a suggested signature keeps ≤ 5 parameters (PLR0913) or says "shape it")
              <numbered list; name the target module explicitly,
              e.g. `src/mscts/bot.py`, not just an area label>
Interfaces: <the issue's Interface; PLAN.md section(s) for internals; allowed deviations>
Out of scope: <what not to touch>
Adapter/Candidate tests assert observable outcomes (chunk contents, spawn), never
              a wire field a Candidate may legitimately get wrong: that is a Divergence
              for the Comparison to report, not a harness assertion.
Done when: <observable condition, e.g. `mise run check` green + named tests exist;
           timings are measured on a committed tree, with `--durations` of the touched
           tests and the load average; a timing claim compares clean main and the branch
           back-to-back on the same host, median of three>
Base: <main commit the brief was written against; the worker first runs
      `git merge --ff-only main` in its worktree; before the PR it rebases onto main
      with `git rebase main --exec "mise run check"`>
Context: <facts, file paths, gotchas the tech lead already knows; reusable scratchpad
         artifacts (jars, generated reports, probe scripts) by path; names a parallel
         brief is introducing that this one must not reuse (check CONTEXT.md); the
         files each parallel worker owns;
         the migration rule if this brief changes anything persisted (cache, files)>
         A rename brief pastes the exact current user-visible lines (`grep -n`: flags,
         help, Report and error text), which get red-first commits; the identifier
         rename, with the PLAN interface blocks and CONTEXT entries, is one atomic
         commit, and the prose sweep is the docs commit; ASCII diagrams and aligned
         comment columns need realigning; it lists the leftover grep hits it expects
         (kept names, tests that pin a word's absence).
         Docs that show changed output move in the same commit as the change; the last
         increment only adds explanations. Name only test tools that are in
         pyproject.toml.
         Name the behaviour to change; name a function only after reading it. Owns
         lists the test fakes and conftests the change reaches. A tier budget states
         the tier's time on main today.
         Scratch files go in `<scratchpad>/<worker letter>/` (the scratchpad is shared),
         with a findings file there that the worker appends each verified fact to.
         ALWAYS include verbatim: "One plain command per Bash call (no `&&`, heredocs,
         `sed -i` or escaped spaces in `--format`); multi-step work goes in
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
- **Your issue, your PR.** Push only your `issue-<n>-<slug>` branch and
  open one PR for it, titled like a commit subject and closing the issue
  (`Closes #<n>`). Never push `main`, merge, or edit `docs/PROGRESS.md`
  or `docs/PROCESS.md`. The tech lead owns them.
- **Apply the Docs delta verbatim** in the same PR as the code, and add
  its examples to the docs check. The site must match the code at every
  commit.
- **Surprises go on the issue.** Anything unexpected that changes the
  issue's scope is a comment on the issue. If the spec cannot be met as
  written (vanilla behaves differently, a fact contradicts it, or it
  conflicts with an ADR), label the issue `needs-decision`, comment what
  you found and the options, and stop that part. Never bend the code or
  the wording to fit. The Retrospective does **not** go on GitHub; it goes
  only in your Worker report.
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
  `python3 /abs/x.py`). Use Edit/Write for code, and to append to a file
  (never a heredoc). Single-quote a Java class name that has a `$`.
  A `;` inside a quoted `sed` script, or a `(` or `$` in an argument, is
  refused too: read a file range with Read (offset, limit), and put such
  arguments inside the script.
- Before deleting a shared helper (`tests/support/`, a fake), grep
  `origin/main` for its users: a parallel branch may have added some.
- **Run tiers through mise**: `mise run test:reference -- <pytest args>`.
  A plain `uv run pytest` uses the host toolchain (Java 21 here), which
  the Reference Adapter correctly refuses unless `MSCTS_JAVA` is set.
- Known tool and type-checker traps are listed in the `red-green` skill.
  Read them first.
- **Commit early, push each commit.** An interrupted agent (API rate
  limit, container restart) loses a worktree that has no commits; push
  your branch after every green commit. The lead resumes an interrupted
  worker by message. Keep research artifacts in your scratch dir, where
  the next worker can reuse them, and a `findings.txt` there (the harness
  refuses a worker's `.md` report files): append each
  verified fact (a javap line, a layout, a live observation) the moment
  you have it. A resumed or compacted worker reads it first and never
  redoes research.
- Rebase onto main only before opening the PR (a rebase rewrites every
  pushed hash), and give commit hashes only in the final report.
- Run `mise run fix` before each test run. Ruff fires FBT003, D102,
  ARG002 and E501 on most new code.
- GitHub goes through the GitHub MCP tools (load them with ToolSearch);
  there is no `gh`.
- Before committing a change to a `Protocol`, grep main for every
  implementer and caller again: a parallel brief may have added one.
- Stay inside the issue's "Owns" list. If you are blocked, or the issue
  is wrong, stop and say so (on the issue, and in the report) rather than
  widening scope.

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
| 2026-10-01 | worker AM (#29 block events) | Wrote a throwaway recorder twice (Control commands in windows, each watcher packet as JSONL); every pin payload came from it | **adopt**: increment 0 of #30's brief commits it as `scripts/research/record.py` |
| 2026-10-01 | worker AM | Making `block_update` strict broke a live test's test-case names, seen only in the reference tier | **adopt** (no change): briefs already run both tiers before the PR, and the lead runs them before merging |
| 2026-10-01 | worker AM | The probe's Self-check failed once in 20 under load after #17 (the watcher missed a `block_update`) | **adopt**: #88 (a joined Bot has the chunks around it), to AO; one failure in six loop runs, only the run under load |
| 2026-10-01 | worker AM | `VEC3` is new; three older inline spellings of it remain | **defer**: the next refactor or audit batch |
| 2026-10-01 | worker AM | Three heredoc slips | **adopt** (no change): the rule stays; the common brief file repeats it |
| 2026-10-01 | lead | Briefs repeated the same 30 lines of rules | **adopt**: `scratchpad/brief-common.txt` holds them; a brief names it and keeps only the issue's specifics |
| 2026-10-01 | worker AL (#17 Control) | `Bot.sync()` was no barrier behind a command (8 of 80 plays), though #18 had passed 20 of 20 once; about 2 h of diagnosis | **adopt**: brief template, a change to a barrier or window is done when its Self-check passes 20 of 20 five times in a row, with a javap account of every queue it crosses |
| 2026-10-01 | worker AL | Pumpkin runs each `chat_command` in its own task, so answers come out of order (71 of 100) | **adopt**: protocol-research skill, measure packet order on both servers (100 runs) and read where the Candidate dispatches the packet before fixing an order contract |
| 2026-10-01 | worker AL | #17 needed #19's generated name list before #19 merged: two cherry-picks and a conflicted rebase | **adopt**: tech-lead skill, a generated file two briefs need lands first, as its own small PR |
| 2026-10-02 | worker AR (#30) | The join matched in 2 of 84 plays: hash-ordered lists the client reads into sets or maps, a clock value, chunk order and light encoding, and a barrier that let later chunk batches and wandering mobs into the window. None was in the spec | **adopt**: the test-group skill (committed now) starts every `test` issue with a 20-play measurement traced by javap; enablers #105 (`observe(until=)`, Control rejoins), #106 (canonical forms), a #22 addition; #30 waits for them |
| 2026-10-02 | worker AR | The spec's timing criterion contradicted ADR-0012, and `join.to_play` cannot be a span | **adopt**: tech-lead skill, check a spec's acceptance tests against every later ADR before briefing |
| 2026-10-02 | worker AR | `probe_loop` has no `loop=` and drops large payloads; a finished probe exits 1; `javap.py` cannot write a file | **adopt**: #107 (helper) |
| 2026-10-02 | worker AP (#97) | The lead asked mid-task for the wait as a public function the next Group imports (a new module, moved tests, a second sweep); the brief's `error` for a Candidate that never empties broke audit H3 | **adopt**: tech-lead skill, a brief names the module and public API of anything the next issue reuses, and states each new failure path's Verdict (Candidate `mismatch`, Reference `error`) |
| 2026-10-02 | worker AP | A status poll cancelled from outside between connect and close leaked its socket; only the mutation sweep found it | **adopt**: red-green Known traps, never cancel a Bot operation from outside; bound it with its `timeout_s` |
| 2026-10-02 | worker AP | The probe Group's `tick freeze` would freeze every later test on the shared Reference | **adopt**: the test-group routine, a Group undoes every setting it changes in a `finally` (committed with #30) |
| 2026-10-02 | lead | The unit tier failed once in #104's integration rebase and passed on re-run; AO saw one failed check loop iteration too | **adopt**: a flake hunt (30 runs under stress) before the next integration; a flake is not a root cause |
| 2026-10-02 | worker AO (#88) | The spec's cause (chunks not yet sent at join) was wrong; reproducing the 1-in-200 failure under load (659 plays) found vanilla answering both barrier requests in one pass | **adopt**: tech-lead skill, a flaky-failure spec names its cause as a hypothesis, and the first increment reproduces it with `scripts/research/probe_loop.py` under load and keeps the failing Transcripts |
| 2026-10-02 | worker AO | The decision's "wait before each extra trip" would have made the cap unreachable; the never-shows-a-gap fake test exposed it | **adopt**: tech-lead skill, a design in a decision comment states what its unit tests assert |
| 2026-10-02 | worker AO | The old fake server answered a pair at once, so the new `sync()` capped in three test files | **adopt**: red-green Known traps, a fake server answers like the real one by default |
| 2026-10-02 | worker AO | CONTEXT.md and the glossary must change together, found only at rebase (second time, after AN) | **adopt**: red-green Known traps; with `mise run commit -- --amend` for a commit a `rebase --exec` stopped on |
| 2026-10-02 | worker AN (#83, #84) | A Group after a joining Group sees its Bots still online (`status/basic` failed 3 of 6 with the probe first): vanilla drops a closed Bot on its next tick | **adopt**: #97, a Group starts only once status says no player is online (before #30 registers `join`) |
| 2026-10-02 | worker AN | Live-tier timings under other workers' load varied 210–395 s; `time_tier.py` cannot show a run passed (second time, after AI) | **adopt**: a timing claim compares clean main and the branch back-to-back on one host (brief template); #98 for `time_tier.py` (helper) |
| 2026-10-02 | worker AN | `mise run commit` said "nothing staged"; an inline pytester run inherits `filterwarnings=error` and needs `asyncio_default_fixture_loop_scope` | **adopt**: red-green Known traps |
| 2026-10-02 | worker AN | Both PRs edited the root conftest's `pytest_plugins` line; the glossary conflicted on rebase | **reject**: one trivial conflict each, and the glossary drift check caught the mismatch as designed |
| 2026-10-01 | worker AL | Deleting `tests/support/commands.py` collided with #19's three new users | **adopt**: brief template, the ownership list names shared test helpers too; Worker contract, grep `origin/main` before deleting a shared helper. The move went to AN (#84) |
| 2026-10-01 | worker AL | ty refuses `dict.fromkeys(...)` as `dict[str, object]`; D205/E501 on docstring summaries, RUF043 on `match=`, C901 on a many-knob fake | **adopt**: red-green Known traps |
| 2026-10-01 | worker AL | `;` in a quoted sed script and `(` / `$` in arguments were refused | **adopt**: Worker contract |
| 2026-10-01 | worker AL | Pumpkin's source is not reachable through the GitHub tools | **adopt**: protocol-research skill, fetch the raw files of the commit the binary's `Commit:` string names |
| 2026-10-01 | worker AL | Wrote its own mutation runner before finding `scripts/mutate.py --batch` | **adopt** (no change): red-green already documents `--batch`; briefs name it |
| 2026-10-01 | lead | A reference test failed once in two runs at #17's merge: a joining Bot got two `player_position`s on the shared Reference | **adopt**: AN investigates it with javap in #84's PR; a retry is not a fix |
| 2026-10-01 | worker AK (#19 item stacks) | 122 components took 17 codec commits and four usage-limit resumes; a scratch javap interpreter made the table mechanical only after an up-front increment | **adopt**: tech-lead skill, a wide table (about 20 entries of one mechanism or more) gets its javap layouts derived and posted on the issue before briefing, by a sonnet triage with `scripts/research/layout.py` |
| 2026-10-01 | worker AK | About eight blind Pumpkin probe runs before the console showed commands had stopped after the fourth slash-named `/give` | **adopt**: #83, a failing tier test shows each Instance's console tail (increment 0 of the first brief after #17) |
| 2026-10-01 | worker AK | `Bot.sync()` does not cover Pumpkin's inventory updates: Pumpkin runs a command about a tick after the barrier answers | **adopt** (no change): #17's `Control.run` waits for its own `tellraw` marker before the sync |
| 2026-10-01 | worker AK | Pumpkin's `/give` parser spins a worker thread for good on a component name with a slash; the fourth stops the server | **adopt** (no change): pinned by a candidate test as evidence; an upstream report is the maintainer's call |
| 2026-10-01 | worker AK | The brief's commit trailer named a different model from the session's own attribution reminder; it followed the reminder | **adopt**: briefs stop restating the trailer; a worker ends commits and the PR body with the lines its own session gives (red-green already says so) |
| 2026-10-01 | worker AK | `test_slot.py` was written after `items.py`, not red first | **adopt** (no change): the mutation sweep (37 of 38 killed, the survivor fixed) showed the tests bite; red first stays the rule |
| 2026-10-01 | worker AK | Used heredocs and `sed -i` late on, under the harness's auto-mode note; the guard refused one compound command | **adopt** (no change): the one-plain-command rule stays, because the guard refuses those shapes whatever the mode |
| 2026-10-01 | worker AJ (#18 observation windows) | The harness refused a `findings.md` | **adopt**: the findings file is `findings.txt` (Worker contract) |
| 2026-10-01 | worker AJ | `git merge --ff-only main` was impossible once main moved | **adopt**: brief template, rebase with `--exec "mise run check"` before the PR |
| 2026-10-01 | worker AJ | Every joining Group's Self-check fails: `login_finished.session_id` is random and `update_tags`' order changes per boot | **adopt**: a shared Comparison rule (a Mask table beside `HEARTBEAT`, a canonical `update_tags`), the first increment of #17, before any joining Group is registered |
| 2026-10-01 | worker AJ | #20's placeholder refused even an empty item stack, so every two-Bot run on Pumpkin stopped; the lead merged #20 after the reference tier only | **adopt**: tech-lead skill, run the candidate tier too before merging a codec change; a placeholder decodes what it can (an empty stack). #19 replaces it |
| 2026-10-01 | worker AJ | `<name>:start` / `<name>:end` Marks become Report timing rows, so the windows use `observe:open` / `observe:close` | **adopt**: briefs reserve the pair for Measurements (ADR-0010 records it) |
| 2026-10-01 | worker AJ | The codec's owner was settled only on resume | **adopt**: brief template, list the files each parallel worker owns |
| 2026-10-01 | worker AJ | A heredoc append and a `$` in a javap class name were refused | **adopt**: Worker contract, append with Edit or Write; single-quote `$` |
| 2026-10-01 | worker AJ | One stats round trip or a play ping is not a barrier on vanilla; two stats round trips are (30/30 on both servers) | **adopt** (no change): recorded in the research note and ADR-0010 |
| 2026-10-01 | worker AJ | A usage limit stopped it mid-increment; push-per-commit and the findings file made the resume cheap | **adopt** (no change) |
| 2026-09-30 | worker AF (#20 entity schemas) | Three restarts, a rate limit and a compaction cost the javap findings, so about a quarter of the session went on repeating research | **adopt**: Worker contract and brief template, a `findings.md` in the scratch dir that gets each verified fact and is read first on resume |
| 2026-09-30 | worker AF | `scripts/mutate.py` floods the terminal with every mutant's failure; a new file seemed to need `git add` | **adopt**: red-green Known trap, redirect it to a log. The `git add` part is wrong: `mutate.py` copies untracked files too |
| 2026-09-30 | worker AF | Ruff's FBT003, D102, ARG002 and E501, and pytest's refusal of `parametrize(enumerate(...))`, cost about 8 fix cycles | **adopt**: red-green Known trap and Worker contract, `mise run fix` before each test run |
| 2026-09-30 | worker AF | The scratch probe broke when main moved (`group_id`), and `Connection.recv` stops on the first undecodable frame | **adopt**: #19 lands the item stacks that caused it; **defer** a committed research probe to after #17 (Control gives it a supported command path) |
| 2026-09-30 | worker AF | Tests that pin recorded payloads or kill mutants were never red | **adopt**: red-green, these are pin tests (say so in the commit); any other new test file runs red before its module exists |
| 2026-09-30 | worker AF | Rebasing 19 pushed commits onto a moved main forced a force-push and staled the reported hashes | **adopt**: Worker contract, rebase only before the PR; hashes only in the final report |
| 2026-09-30 | worker AF | The worktree guard refused heredocs, `sed -i`, `&&` and an escaped space in `--format` | **adopt**: briefs list those shapes beside "one plain command per Bash call" |
| 2026-09-30 | worker AF | The wiki was wrong in four layouts; javap was right every time | **adopt** (no change): protocol-research already says the jar wins |
| 2026-09-30 | worker AF | A committed layout printer (`body.py`) would have saved the most time | **adopt**: increment 0 of #19's brief commits it as `scripts/research/layout.py` |
| 2026-09-30 | worker AI (#16 Bot fidelity) | The brief put the brand in `join()`; only `Replies` keeps vanilla's order | **adopt**: brief template, name the behaviour, and a function only after reading it |
| 2026-09-30 | worker AI | "The join tests pass unchanged" could not hold: they pin what the Bot sends | **adopt** (no change): the worker grew them; the template's new Owns rule covers it |
| 2026-09-30 | worker AI | No Unsigned Byte in `schema.py`, so `configuration.py` has a local one | **adopt**: #19's brief moves it into `schema.py` as `UBYTE` (and `animate` uses it) |
| 2026-09-30 | worker AI | The wiki's Player Loaded section is wrong for 26.3 (the 60 ticks are the server's timeout) | **adopt** (no change): recorded in the research note |
| 2026-09-30 | worker AI | Edited `tests/net/fakes.py`, a Bot test and a conftest outside Owns | **adopt**: brief template, Owns lists the fakes and conftests the change reaches |
| 2026-09-30 | worker AI | `scripts/time_tier.py` prints timings but not pass or fail; G5 was already broken on main | **defer**: a tooling chore with the parallel reference tier (G5); the brief template now states the tier's time on main |
| 2026-09-30 | worker AH (#8 test cases) | The spec's example name (`status_response.description`) disagreed with its own rule 1 (the compared path is `json_response.description`); the largest design cost | **adopt**: tech-lead skill, check a spec's examples against what the code emits today before briefing |
| 2026-09-30 | worker AH | The brief named hypothesis, which is not a dependency | **adopt**: brief template, name only test tools in pyproject.toml |
| 2026-09-30 | worker AH | Report output changed in increment 4, so docs samples had to move with it, not wait for the docs increment | **adopt**: brief template, docs that show changed output move with the change |
| 2026-09-30 | worker AH | The container restarted after a commit but before its push | **adopt**: Worker contract, push after every green commit; GitHub via the MCP tools |
| 2026-09-30 | worker AH | pytest collects an imported public `test_case` function as a test | **adopt**: red-green Known trap (import it under an alias) |
| 2026-09-30 | worker AH | A failing `assert s in out` truncates `out`; Write/Edit turn `\u` escapes into literal characters; `mutate.py --batch` output interleaves pytest output | **adopt**: red-green Known traps |
| 2026-09-30 | worker AH | A new required `Divergence` field meant editing ~20 constructions in 8 test files | **adopt**: #18's brief moves test Divergences behind one helper in `tests/compare/build.py` |
| 2026-09-30 | worker AH | No Codec call lists packet names per State; `_in_more_than_one_state` probes `packet_id` | **adopt**: #29's brief adds `Codec.names(state, direction)` and simplifies it |
| 2026-09-30 | worker AH | Listing every compared field cost +55% on a huge packet before tuning (now +10–23%) | **defer**: a compare benchmark with a budget when a Group compares chunks (#22) |
| 2026-09-30 | worker AH | Report samples are copied by hand into three pages | **defer**: #14 (docs checks), as for AG |
| 2026-09-30 | worker AH | "Proposing a test" says "A test is a Group", beside the term test case | **adopt**: the lead reworded it |
| 2026-09-30 | lead (incident) | An account usage limit stopped AF (#20) mid-increment; its two commits and uncommitted edits survived in its worktree, and SendMessage resumed it after the reset | **adopt** (no change): "commit early" held; resume an interrupted worker by SendMessage rather than re-briefing |
| 2026-09-30 | worker AG (#11 wording) | No docs check exists for Report examples, though the contract says to add examples to it | **defer**: maintainer issue #14 (docs checks), scheduled with the output issues #9 / #10 |
| 2026-09-30 | worker AG | The brief paraphrased a Report line ("N changes on the wire") instead of pasting it | **adopt**: brief template, a rename brief pastes the exact current lines (`grep -n`) |
| 2026-09-30 | worker AG | Sorting each leftover grep hit into rename / keep / reword took most of the time | **adopt**: brief template, a rename brief lists the leftover hits it expects |
| 2026-09-30 | worker AG | The contract puts interface edits in the same commit, the brief put docs last | **adopt**: brief template, PLAN interface blocks and CONTEXT entries go in the rename commit; the prose sweep in the docs commit |
| 2026-09-30 | worker AG | ADR-0007's file name keeps "wire", so the site test exempts link targets | **reject**: ADR files are records and keep their names |
| 2026-09-30 | worker AD (#7 rename) | A pure identifier rename cannot be red-first; only the user-visible strings (flag, help, Report and error text) can, and the brief did not list them (15 min) | **adopt**: brief template, a rename brief lists the user-visible strings; the identifier rename is one atomic commit |
| 2026-09-30 | worker AD | ASCII diagrams and comment-aligned signature blocks broke when names changed length (10 min) | **adopt**: brief template, a rename brief says to realign them |
| 2026-09-30 | worker AD | The brief's "grep is clean" cannot hold: tests that pin a word's absence contain it | **adopt**: brief template, absence tests are expected hits |
| 2026-09-30 | worker AD | A pytest path list that revisits a directory lost its conftest fixtures | **adopt**: red-green Known trap |
| 2026-09-30 | worker AD | "group" is now a term and an ordinary verb in the same pages | **adopt**: writing skill, "Keep the terms for the terms"; #8's brief re-reads the docs for it |
| 2026-09-30 | worker AD | Existing error-message tests matched only ids, so wording was unpinned | **reject** (no change): AD pinned them; briefs already require red-first user-visible text |
| 2026-09-30 | worker AE (#15 play package) | ty rejects an annotated assignment from `getattr(…, default)` (unsound-assignment); one refused commit | **adopt**: red-green Known trap |
| 2026-09-30 | worker AE | `Schema` compares by identity, so an equal-looking expected mapping never matches | **adopt**: red-green Known trap |
| 2026-09-30 | worker AE | Mutations of import-time code break collection, so `mutate.py` says INVALID, not KILLED | **adopt**: red-green Known trap (select only the new test file; read INVALID's detail) |
| 2026-09-30 | worker AE | A play submodule with neither mapping (or a misspelt one) is silently ignored | **adopt**: #20's brief makes it a `SchemaError` at import |
| 2026-09-30 | worker AE | The brief's suggested test seam (merge an iterable of `(name, module)`) needed no deviation | **adopt** (no change): keep naming the test seam in briefs |
| 2026-09-26 | worker AC (status classification, Report audit) | `javap.py` has only the client jar; DFU and Gson had to be extracted from the bundle by hand | **defer**: already issue #6 (helper) |
| 2026-09-26 | worker AC | Reclassifying to wire-only turned the Report's wire-only line into two truncated 100+ char JSON strings; fixed by comparing status JSON at JSON paths | **adopt**: a brief that changes a classification also checks the live Report text |
| 2026-09-26 | worker AC | Tests used unknown status keys (`{"a":1}`) as stand-ins, which the new canonical form drops | **reject** (no change): the tests now use real field names |
| 2026-09-26 | worker AC | Wrote code before the test once; covered by a mutation batch | **reject** (no change): the rule stands |
| 2026-09-26 | worker AC audit | Wire-only examples hid the rest silently (4 differ, 3 shown) | **adopt**: the lead shows 5 and says "and N more" (f755d8b) |
| 2026-09-26 | worker AC audit | MD1: `blocked` treats a prerequisite with only wire-only Divergences as failed | **defer**: decide with the first Scenario that has `requires` (join) |
| 2026-09-26 | worker AC audit | Low findings: error-repetition spans in Timings, summary under an error, p95 = max below 20 values, unsettled wire-only not flagged, exit code always 0, a late RunnerError loses the Report, `failed` line lacks the Bot | **defer**: listed in `docs/audits/2026-09-26-report-path.md` |
| 2026-09-26 | worker AB (first Report) | status/ping required status/basic to match, so any Candidate with a status difference lost every status.rtt timing | **adopt**: the lead dropped the prerequisite (status/ping asks for the status itself); briefing rule, a Scenario that exists to measure never requires another's exact match |
| 2026-09-26 | worker AB | A ~130-line heredoc to a file was refused by the sandbox | **reject** (no change): the Worker contract already says to Write the script |
| 2026-09-26 | worker AB | RUF001 on `›`; ty misses a flag set in `except` (redundant-condition); ty rejects `zip(*generator)`; ISC004 again | **defer**: red-green Known traps (session 3 parks process work) |
| 2026-09-26 | worker AB | The live-proof increment caught out-of-order progress lines and unplayed Scenarios being silent | **adopt** (no change): keep a live-proof increment in every user-facing brief |
| 2026-09-26 | worker AB | A batch mutation sweep found an untested span-pairing rule | **defer**: require one sweep per new module in the brief template |
| 2026-09-26 | worker AB | `"favicon": null` is reported observable; unverified whether the client reads it as absent | **adopt**: worker AC verifies it (and Pumpkin's `enforceSecureChat` spelling) from the jar |
| 2026-09-26 | worker AB | The side that plays first shows a higher status.rtt median (warm-up bias) | **defer**: M7 fairness, alternate the order per repetition |
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
| 2026-09-30 | Test proposals: the `test` issue template (`.github/ISSUE_TEMPLATE/test.md`), "Proposing a test" in `docs/contributing.md`, and `test` / `enabler` labels. Infrastructure several tests need is one shared `enabler` issue; a `test` issue gets `ready` once its enablers land. Evidence lives in `docs/research/2026-09-30-gameplay-survey.md` | Maintainer: explore what to compare between servers (lighting, spawning, combat, mob simulation, chunk loading, …) and make adding a test a standard process that independent agents can pick up |
| 2026-09-27 | ADR-0009: the docs site is the spec; GitHub spec issues are the queue; one PR per issue, owned by its worker; scope surprises as issue comments; retrospectives stay private to the lead; docs examples are checked by tests | Maintainer: define the interface and wording in the docs, have agents make the code match, and parallelize across issues |
| 2026-09-26 | Commits go through `mise run commit` (check, then commit only if green) | The piped-check slip happened twice |
| 2026-09-26 | Independent Next items may be delegated to the maintainer's helper agent via `helper-ready` GitHub issues | Maintainer: an optional helping hand; Claude stays primary |
| 2026-09-26 | ADR-0008: explicit idempotent installs (`mscts adapter install`, `--from`), an honest prompt, a checksum-pinned registry, Adapter authoring guide + conformance kit, DX goal G6 | User direction: an elegant, honest DX; installs never hidden in test runs |
| 2026-09-26 | ADR-0007: wire-only Divergences are reported separately and excluded from scores; the Pumpkin Adapter writes native world saves | User decisions |
| 2026-09-26 | ADR-0006: catalogue of differences; exact/tick-exact/statistical Scenarios; Masks only for non-gameplay ids; commands-only Fixtures | User direction: surface every difference (randomness, redstone, glitches) without hiding any |
| 2026-09-25 | Adopted the tech-lead/worker model with mandatory retrospectives | User direction: the lead steers, workers execute, and the process optimises itself |
