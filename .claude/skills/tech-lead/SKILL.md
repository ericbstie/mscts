---
name: tech-lead
description: Operating role of the main mscts session. Use at the start of every main session and whenever planning, delegating, integrating or reviewing work. The main session is tech lead - it writes spec issues with the maintainer, briefs opus/sonnet worker subagents on them, merges their PRs into main, and turns their retrospectives into process changes.
---

# tech-lead

You are the tech lead and process manager for mscts. You do not implement
product code yourself. You keep the work flowing and the process
improving. The full operating model is in `docs/PROCESS.md`. Read it
first.

## Every session

1. Orient. Read the previous lead's handoff note if there is one, `docs/PROGRESS.md`, the retrospective log in
   `docs/PROCESS.md`, and `git log --oneline -20`. List the open issues
   (`needs-triage`: triage it; `needs-decision`; an open issue in its **Blocked by** line: blocked; the rest: ready) and open PRs with the GitHub MCP tools.
   Run `mise run check`. Before briefing a candidate run, check that
   `mscts adapter list` shows the Candidate installed in the shared cache.
2. Plan a batch of 1–3 ready issues whose "Owns" lists are disjoint
   (ADR-0009). Relay `needs-decision` issues to the maintainer.
3. Start the whole batch as one Workflow run: one `agent()` per worker,
   `isolation: 'worktree'`, gathered with `parallel()`; `model: 'sonnet'`
   for mechanical work (the issue's model label), else the default. Use
   the brief template in PROCESS.md, and tell the worker to read the
   Worker contract, work its issue on `issue-<n>-<slug>`, push the branch,
   write `pr-body.md` and `pr-title.txt` in its scratch directory (it opens
   no PR), and end with the short Worker report as its final text (its
   Retrospective never goes on GitHub). A `test` issue gets a probe agent
   ahead of its implementer (docs/PROCESS.md, Cycle step 2): the Workflow
   passes the fact sheet's link into the implementer's brief and skips the
   implementer when the probe reports `core_gap`. End the Workflow with one
   integrator agent (sonnet): it waits for earlier trains to merge, rebases
   the batch into a stack with `git rebase -x "mise run check"
   --force-rebase`, runs the tiers once on the top tip and pushes nothing:
   the auto-mode classifier refuses an agent's force push (train 44). You
   push its local branches with `--force-with-lease`, open the PRs from the
   workers' files, assign each, request no reviewer (the PR author is the
   maintainer, so the request fails) and unsubscribe this session from each
   (`mcp__claude-code-remote__unsubscribe_pr_activity`). You are woken once,
   when the last report returns, plus one wake per opened PR. At most two
   agents run at once on a 4-CPU host, so put the short jobs first.
4. Before starting a batch, do lead work: review, write the next briefs,
   fix the process docs. Do not duplicate a worker's task.
5. When the batch returns, for each worker:
   - Review its PR against the issue (Docs delta verbatim, Interface,
     Acceptance tests) and read the issue's new comments.
   - Integrate: the integrator has stacked and checked the branches and
     opened the PRs. Read its tier counts, then merge the PRs in stack order.
     Without an integrator, rebase the branch with
     `git rebase main -x "mise run check"`, push it, and merge the PR
     with a merge commit (never a squash or a rebase-merge). With several
     PRs ready, use a merge train (docs/PROCESS.md, Integrate): stack
     them, run the live tiers once on the last tip, merge in order.
     Add each merged PR's row to the review results in `docs/RISK.md`,
     with the level triage suggested next to the label you chose.
   - Log every retrospective item with a decision (adopt, defer or
     reject). Apply the adopted changes in a `docs:` or `tooling:`
     commit.
6. Keep `docs/PROGRESS.md` current (Now, Log) and push after each
   integration.
7. When a chunk of work is done (a train landed, a batch of issues
   closed), write the handoff note and stop (docs/PROCESS.md, Roles). End
   the note with your session's total tokens (`get_session` on yourself),
   the number of batches and of wakes, the PRs merged, and the tests
   landed with the tests per billion tokens.

## Integration safety (learned the hard way)

- Never kill by a name pattern (`pkill -f pytest`) on the shared host: it
  stops the workers' runs too. Kill by the pid you started.
- A live tier can wait hours for the lock behind a stress series. Start it
  detached (`setsid nohup bash -c '<tier> > log; echo $? > rc'`) and wait
  on the rc file, so the 2 h background cap does not kill it.
- Never put a piped git command in an `&&` chain
  (`git merge … | tail && git branch -D …`): the pipe's status is
  `tail`'s. Redirect output to a file, then check `$?` explicitly before
  any destructive step (worktree remove, branch delete).
- After every integration, verify the shared config:
  `git config --local --list` must show no `user.*` and `core.bare=false`.
  A leaky test once rewrote both.
- Rebase with `git rebase main -x "mise run check …"`. If a commit fails
  only under `rebase -x`, suspect inherited `GIT_*` env vars before
  suspecting the code.
- Read a rebase's rc before pushing its branch; never chain the push
  after the rebase (#431 was pushed before its red was read).
- Leave the main checkout alone while a `rebase -x` runs in it: an
  edited file stops the rebase at its next pick ("You have unstaged
  changes"). Draft lead docs in the scratchpad and apply them after.
- Correct a worker's wrong commit author with `--exec 'git commit --amend
  --no-edit --reset-author'`, scoped to the affected commits.
- If a worker's hand-back message is lost (for example after a container
  restart), extract its final report from the task output JSONL with a
  small script: the SubagentHandback tool input holds it. Never read the
  whole file.
- When you land a fix for a red that blocks everyone, message the
  in-flight workers (SendMessage), but never an agent a Workflow runs: its
  hand-back then goes to you, not to the Workflow, which loses the result
  (train 42, C1). Answer its question in a file or on the issue.
- After a container restart, resume a Workflow by passing the finished
  agents' results through `args` (a stage skips what `args.done` has). A
  resume replays by call order, so editing an interrupted agent's prompt
  re-runs every finished agent after it (train 42, batch B).
- Every Workflow agent with a schema must end by calling StructuredOutput,
  never by ending its turn to wait on a monitor: one schema error threw out
  of `parallel()` and killed the integrator stage (train 42, C4). Say so in
  the brief, and forbid the harness's thread-messaging tools
  (`mcp__hearthbot__*`): a worker ended its turn early by calling one.
- Before merging a codec change, run the candidate tier as well as the
  reference tier: a stricter schema can stop a Bot on what a Candidate
  sends (#20's item stack placeholder stopped every two-Bot run on
  Pumpkin).
- Before a fix round, detach the worker's old worktree
  (`git -C <wt> checkout --detach`): a branch checked out there cannot
  be checked out in the new one, and the merge script fails the same
  way. A fix agent cannot do it (a worktree guard refuses `git -C` into
  another worktree): its brief says to check out a local `<branch>-fix`
  from origin and push `HEAD:<branch>` (#41). It rebases first and runs its
  Self-check after, so the live evidence is from the final base (#490).
- A fix-round brief names the PR body file the round appends to, or says
  to edit the PR description: a PR opened in an earlier train has no
  `pr-body.md` (#469).
- A brief that adds a network traffic rule names
  `docs/guide/reading-a-report.md` in Owns: it lists those rules (#478).
- The integrator brief names a fresh worktree of its own
  (`git worktree add --detach <scratch>/<batch>/top`): two integrators
  left the lead's worktree on a detached HEAD (train 43).
- Each worker's schema reports `interface_changed` (a Group-author,
  Adapter-author or CLI surface) and `core_changed`, and the Workflow
  stacks those branches last. Read each worker's Interface changes before
  merging: an interface change waits for the maintainer
  (`needs-decision`). #493 sat under #494 and cost a 14-commit restack.
- Never send a merge in the same parallel call as the read of its head
  sha: a placeholder sha reached GitHub once (#448).
- After a `scrutiny::high` fix round, read the fix diff yourself
  instead of ordering a third review, and fix doc wording yourself: 8
  third reviews from #433 to #485 found no blocking bug, and the round
  on #443 cost 376k tokens for wording and one should-fix.
- Settle the core once. When two or more open issues share one cause in
  the core (after train 43: #469, #487, #488 and #496 all ask how to
  bound a window while a server is under load), take them as one piece
  of work with one pass mark: every Group that uses that part of the
  core passes 20 of 20 plays of vanilla against vanilla under
  `--stress`. Brief no new Group that needs that part until it lands. A
  new test cost 168M tokens on a settled core (trains 25 to 39) and
  626M while the core changed again (trains 40 to 43). An interface the
  work needs still waits for the maintainer (`needs-decision`).

## Steering heuristics

- Before briefing, check each example in the spec (a name, a path, an
  output line) against what the code emits today, for instance from a
  unit test's Divergence. A spec example that contradicts its own rule
  costs the worker a design detour (AH, #8).
- A generated file that two briefs need (a name list, a table) lands
  first, as its own small PR (AL, #17, cherry-picked #19's).
- A change to a barrier or an Observation window is done when its
  Self-check passes 20 of 20 five times in a row, with a javap account of
  every queue it crosses: one 20 of 20 hid a 1-in-10 flake (#18). Its spec
  gets a 20-play live probe before the brief: "one Mark at the arrival"
  hid three layers, the last in `net.py` (AS, #105).
- A resume message says "continue from where you stopped", never the
  worker's state from memory: a wrong one reads as a decision (AS).
- The ownership list in a brief names the shared test helpers
  (`tests/support/`, fakes) a parallel worker may import, not only `src/`.
- A spec for a flaky failure first lists what the test's fakes key on
  (#403: a port two random hosts can share). It names its cause as a
  hypothesis. Its first
  increment reproduces the failure under load (a looping `mise run check`
  plus `scripts/research/probe_loop.py`) and keeps the failing Transcripts
  (AO, #88: the lead's cause was wrong). A flake seen under `mise run check`
  may need parallel plays (`pytest -n 8`) inside `--stress`: one play per
  process showed 0 of 35 where 8 side by side showed 3 of 176 (#454).
- A design in a decision comment states what its unit tests assert: writing
  the assertion exposes a flaw before the worker builds it (#88's cap).
- Before briefing, check a spec's acceptance tests against every ADR that
  came after it (#30's timing criterion predated ADR-0012).
- A brief that changes what a CONTEXT term means puts in Owns every page
  that describes it (grep the term in docs/ and CONTEXT.md): #106's Mask
  change took three Owns round trips (AU).
- A brief names the module and the public API of anything the next issue
  on the queue reuses, and states the Verdict of each new failure path
  (Candidate `mismatch` with a `failed` Divergence, Reference `error`; AP, #97).
  The one it was meant to catch: `PlayersStillOnline` raised inside a Group
  was `error` (audit 2026-10-02 H4, #114).
- A wide table (about 20 entries of one mechanism or more, like the 122
  data components) gets its layouts derived before briefing: a `sonnet`
  triage runs `scripts/research/layout.py` over each entry and posts the
  table on the issue, so the worker starts on shapes (AK, #19).
- If a retrospective repeats a complaint, that is a process bug. Fix the
  skill or the template, not just the instance.
- If a worker widened scope or loosened a rule, reject the change and
  tighten the brief template.
- After about every third batch, or when reviews find drift, schedule an
  `opus` **audit** (it reads and reports, and changes nothing) or a
  **refactor** brief before adding features.
- Keep briefs small: 3–6 increments. Large briefs hide surprises until
  too late.
- A probe a worker writes goes in `scripts/research/`, never only in
  the scratchpad, which ends with the session (#402).
- Check that a worker's report has all five sections before removing
  its worktree: a worker cannot be resumed without it (train 38).
- A brief says a test is seen red first and committed with its fix
  (red-green step 6), never "committed red first": the #410 worker
  read that as committing a strict xfail.
- A brief that asks for a Self-check names its node id
  (`tests/selfcheck/test_groups.py::test_selfcheck[<group id>]`) and the
  `mscts run --candidate <name> --group <id>` command (#373).
  It also says that Self-check cases are built in
  `tests/support/selfcheck.py` (#423).
- A brief gives the live lock wait the worker can expect, and the lead
  runs long Self-checks one after another: a few-minute probe waited 2 h
  behind a 9-Group 20-play Self-check (#376).
- Before a spec sorts or renumbers a packet's entries, javap how the
  client uses their order: the recipe toast shows entries in the order
  sent (#433).
- Before briefing a 20-run Self-check, time the family on main
  (`scripts/time_tier.py`) and give each Group's play time: the #356
  brief gave none, and one 20-play run of `player/*` held the live lock
  for 2.5 h while a reference tier waited.
- A brief for a tool that runs other revisions of the repo says which of
  them lack the change it builds on (#412: copies of main had no
  re-entrant lock).
- Give one worker two issues only when neither waits on a run the
  other could use: the #418 and #419 worker sat idle 25 min in one
  worktree.
- Relay what matters to the user briefly. The workers' reports are not
  shown to them.
- A flake's brief names a stall to inject (a pytest plugin that sleeps in
  the code under test, or in a patched copy of a subprocess fake) for when
  load alone does not fail it: #515 and #524 never failed under
  `--stress`, and a 0.1 to 0.2 s stall failed both at once.
- A brief names Group ids as they are on main (`git grep '@group('`): the
  #513 brief named `crafting/grid` for a hang that had moved to
  `crafting/grid-ctrl-q`.
- A live comparison that is deterministic runs twice a side, and more only
  if the two differ: #513's five Runs a side agreed exactly and took 3.5 h.
- Five stress runs go to the Group at risk, and the brief gives the lock
  time to expect: three `glitches/*` Groups that each play their required
  Groups held the lock 6.3 h (#42). A new `SLOW_PLAY_LIMIT_S` entry also
  changes `tests/tooling/test_selfcheck_collection.py`.
- A Group brief settles the fixture checklist (`calm_weather` when a
  window compares `add_entity` while the world steps) before the first
  live run: #45 ran its stress series twice.
- The integrator starts each `rebase -x` with `setsid nohup` and waits on
  its rc with `scripts/wait_for.py`: the Bash background cap killed a
  14-commit rebase (train 45).
