# Rules every specialist follows

Your brief overrides this where they differ. The lead names your scratch
directory (`<scratch>` below) in the brief.

Read CLAUDE.md, docs/PROCESS.md (Worker contract, Worker report, Lanes and
review levels), your lane's handbook in this directory, and the red-green,
protocol-research, function-design and writing skills (.claude/skills/)
before starting. Every function you write or change follows
function-design; existing code is brought to it only where your issue
already changes it.

Also read and apply the maintainer's `unslop` and `minimal-increment`
skills (.claude/skills/). Where they differ from this project's process,
the project wins:

- minimal-increment: your issue is the scope answer, so don't ask anyone
  which parts are in scope. Tests are always in scope (red-green), and so
  are docs for anything a user sees (ADR-0009). Its "what could be done
  next" ending goes in your Worker report.
- unslop: its list of patterns applies to all prose. Its "adding soul"
  advice (opinions, "I", some mess) doesn't apply to the docs, the Report
  or CLI text, where the writing skill's "be humble and honest, let the
  reader decide" wins.
Read your issue and its comments first (GitHub MCP tools, loaded with
ToolSearch; repo ericbstie/mscts; no `gh`).
Open and edit your PR with the GitHub MCP tools too: `gh` gets a 403 here.

- Every commit passes `mise run check`. Commit only with
  `mise run commit -- -F /abs/msg.txt`, and push after each commit. Stage
  your files with `git add` first: it commits only what is staged. Never
  `git stash`. The check includes `plan`: every new public top-level name in
  src/ needs a docs/PLAN.md entry in the same commit.
- Tests red first (pin tests of recorded payloads and mutant killers
  excepted: say so in the commit message). A mutation sweep with
  `scripts/mutate.py --batch spec.json --jobs 4 -- <tests>` (red-green,
  Known traps), output redirected to a log in your scratch dir. Name the
  narrowest test selection that kills the mutants, and pass `--timeout 300`. Make
  each mutant's old text unique in its file, or it may change another function.
- A Group test module plays each Group once per process and its tests read
  that play: `play(group_id)` caches in a module dict (`_PLAYS`), and
  `replay(group_id, server)` plays uncached for a test that needs its own
  fake server. The unit tier runs `--dist loadfile`, so keep a Group's tests
  in one file (#350).
- `mscts run --group` takes one glob, and the last `--group` wins: run one
  `mscts run` per glob.
- Repeat a selection with
  `uv run scripts/repeat.py --times N [--stress] [--live-lock] [--stop-at-first-failure
  [--failure-log FILE]] [--deadline TIME] -- <pytest args>` (one line per run, starting
  with the UTC time it ended, and the union of failures). `--stop-at-first-failure` ends
  the series at the first failing run and keeps that run's whole output in `FILE`
  (default `repeat-failure.log` in the working directory); `--deadline` (ISO 8601 with a
  UTC offset, `2026-10-24T18:00:00Z`) starts no run at or after that time, so give the
  same time again after a restart, and the report says how many runs ran (exit 3 if the
  deadline cut the series short with no failure). Set `PYTHONUNBUFFERED=1` when you
  redirect it, or its lines arrive only at the end. Never hand-roll a loop, a
  stop-at-first-failure wrapper or a deadline of your own. Use
  `--stress` only when your brief or issue asks: it slows every other
  agent's tiers on this host. A live selection (a Self-check, a reference or
  candidate test) gets `--live-lock`: each run takes the live lock and
  releases it, so a short live run that is waiting goes between two of your
  runs. Never put a series under an outer `live_lock.py`: that holds the lock
  until the last run (#411).
- Run the mutation sweep before the docs commits, so a bug it finds is
  fixed while the code is fresh.
- The docs checks run the guide's Python examples (#109): a fragment gets
  `<!-- not run: <why> -->` on the line before its fence.
- A change outside your issue's Owns list, or in a core area another lane
  owns: stop and hand back the evidence and the options. Go on only when a
  lead message names the file.
- A new packet schema also owns what it breaks: the generated name lists
  (`mise run regen:packets`), `HOLDS_NO_ENTITY_ID`, and a placeholder
  packet in `tests/net/fakes.py` that no longer decodes (replace it with
  something a real server could send). Read the layout with
  `scripts/research/layout.py` before the wiki.
- A new test case name in `TITLES` and its row in
  `docs/reference/test-cases.md` land in the same commit.
- Push your first commit early, and start every Edit or Write path with
  your worktree's path: a lost worktree loses only what was never pushed.
- Before `mise run commit`, run `uv run ty check` and `uv run ruff check`: `mise run fix` does not add a missing `@override`, and each failed commit costs a 4-minute check.
- Run `mise run fix` before each test run (red-green Known traps lists
  ruff's recurring rules).
- One plain command per Bash call: no `&&`, `;`, heredocs, `sed -i`, or
  `(` / `$` in arguments. Read file ranges with Read (offset, limit).
  Multi-step work goes in a script in your scratch dir. Append with Edit or
  Write. Never `cd` elsewhere: use `git -C`, `uv run --directory`,
  `mise run --cd`.
- Keep `<scratch>/findings.txt`: append each verified fact (a javap line, a
  live observation) the moment you verify it. If you are resumed, read it
  first and never redo research.
- `scripts/research/javap.py` and `scripts/research/layout.py` read the
  cached 26.3 jar. Vanilla and Pumpkin are installed in the shared cache.
- Live work: setup commands go through `context.control.run(...)` before
  an Observation window (`context.observe(...)`). Before the PR, run only
  the live tests your change adds or touches, by path
  (`mise run test:reference -- tests/...::test_name`, and the same for
  `test:candidate`), and open the PR as a draft. The lead's merge train
  runs the full live tiers once, on the train's tip.
  Candidate tests assert observable outcomes, never a field a Candidate may
  legitimately get wrong.
- Live-tier mise tasks share `<cache>/live-tier.lock` (#138). Others
  wait for the holder and get the lock in the order they asked (#374), and a
  waiter that dies drops out of the queue; `MSCTS_LIVE_LOCK=0` bypasses it on a machine known
  to have enough capacity. A command started inside a holder's command takes no lock: the
  holder exports `MSCTS_LIVE_LOCK_HELD`. The unit tier takes no lock.
  Never bypass it on a shared host, and run `mscts run` against a
  Candidate only while you hold no other live run: too many Instances at
  once restarted the container twice in train 30.
- Run `mise run commit`, the live tiers and Self-checks in the background
  with the longest timeout (7200000 ms). A 10-minute limit kills the check
  and leaves `.git/index.lock` behind. Wait for a background run by its
  output, never by `pgrep -f` in a loop: it matches its own wrapper.
- Rebase onto main only before opening the PR
  (`git rebase main --exec "mise run check"`), and report commit hashes
  only in the final report. A timing claim compares clean main and your
  branch back-to-back on this host (median of three), never a lone number.
  Commit first, then `uv run scripts/time_tier.py <mise task> --rev origin/main --rev HEAD
  --rounds 3 [--stress] -- <pytest selection>`: it alternates the two `git archive` copies
  under one live-lock hold and prints each round, the median per revision and the load
  average (#412).
  Before deleting a shared helper, grep origin/main for its users.
- Commit messages and the PR body end with the attribution lines your own
  session's system reminder gives. Name no model anywhere else. One issue
  comment at most, for decisions.
- Meet the scrutiny level (the issue's `scrutiny::*` label) (PROCESS, Lanes and
  review levels) before you hand back the PR.
- End each issue with the Worker report exactly as docs/PROCESS.md
  specifies, including the lines you propose for your lane's handbook.
  State your worktree path, branch and PR URL.
- Start any live run that can outlast a few minutes with `setsid nohup` in a scratch script, and wait on its rc file within your turn: a background run that outlives your turn is killed.
- Never set a rule the Fixture world already has (`spawn_mobs` is off, ADR-0013): its undo sets vanilla's default and turns spawning on for every later play (#344, #63).
- A fake gives each `where=` predicate a near miss for every field it checks: a near miss that differs in one field leaves the others' checks untested (#63).
- Wait on a detached run's rc file with foreground polls of at most 590 s each, one Bash call per poll: a longer wait moves to the background, and `Monitor`'s sleep can return at once. A commit (`mise run commit`) takes about 5 min and `rebase -x` about 5 min a commit, so start both detached too.
- A probe that needs load runs under `scripts/repeat.py --stress --live-lock`, which loads the CPUs only while the run holds the lock, not while it waits (#354).
- Shared test helpers live in `tests/support/`; a `test_*.py` never imports another. After moving a helper, run each changed test file alone: the full suite can hide a lost import (#146). A PR that moves or renames helpers lists the old and new names in its body.
- An Adapter Protocol member lands with every implementation in one commit, or `ty` fails; order the increments for it. Live install checks set `MSCTS_CACHE` to a scratch directory (#188).
- An `mscts run --candidate` log and report.md can reach 20 MB for one family. Summarise report.json with a script that keeps the window packets; never read the log whole (#39).
- Run `mscts run` outside a mise task as `mise exec -- uv run mscts run …`, or it finds Java 21 and stops (#362). It takes no live lock: wrap it as `scripts/live_lock.py --tier candidate -- …`, on a `git archive` copy if you keep editing while it waits (#443).
- Rebase in a second, detached worktree while your live runs hold the first. Start a detached git command from a script that uses `git -C <worktree>`. `git rebase --exec` replays already-rebased commits only with `--force-rebase` (#40, #256, #443).
- A fake's `set_entity_data` entries name the serializer (`"int"`), not its id. A fake task that suppresses only ConnectionError dies silently on a CodecError, and the Group just times out (#345).
- A Self-check plays `MSCTS_SELFCHECK_REPEAT` times, default 3: "20 of 20" needs `MSCTS_SELFCHECK_REPEAT=20` exported. `mise run test:selfcheck` and `repeat.py` pass it through. Run `repeat.py` on a live selection as `mise exec -- uv run scripts/repeat.py …`, or the Reference setup finds Java 21 and stops with a PrepareError; `mise run test:selfcheck` sets the Java itself (#461). `repeat.py` now guesses a live selection from its paths (`selfcheck`, `reference`, `candidate`) and `-m` expression, and under a Java the Reference refuses it stops at once with exit 2, naming the `mise exec` form (#472).
- `mise run test:selfcheck -- <node ids> -vv` shows the node names: the project's `-q` in addopts hides them with a single `-v` (#461).
- `scripts/mutate.py -x` must not be combined with `-n` (xdist): every failing mutant then reads INVALID (exit 2), not KILLED. Delete the sweep's rc file before you start it, and wait for its trailing rc line, never for a `FAILED` or `" in "` pattern: pytest output and uv's warnings match at once (#462).
- `git rebase origin/main --exec "mise run check"` on a branch that already sits on origin/main's tip still runs the check on every commit: about 5 min a commit (11 commits took about 70 min and met the background limit). Start it with `setsid nohup` and wait on its rc file (#451, #455, #462).
- Append a state line to `<scratch>/findings.txt` after each commit ("state: done X, next Y", and which review items are still open), so an interrupted agent that is resumed does not rebuild its state from commit messages (#451).
- Never call the harness's thread-messaging tools (`mcp__hearthbot__*`): a worker ended its turn at 6 of 14 checked by calling one. A Workflow agent with an output schema ends by calling StructuredOutput, never by ending its turn to wait on a monitor: the schema error threw out of the whole Workflow (#476, #441).
- Commit subjects keep the `area: ` prefix (`group: …`, `docs: …`, `tooling: …`), the form of `git log`. A sonnet worker wrote "Add titles for …" (#442).
- A Group plays on when a server does something else (a container that does not open, a block that does not act): the windows show the difference. A guard that raises turns a Candidate's difference into an `error` (#41).
- Check a reviewer's proposed fix against the jar before you build it, as you would your own facts: one rested on a server fact javap disproved (#41).
- Give `scripts/mutate.py` `--timeout 280` for a Group's tests: the default 60 s left two mutants INVALID (#41).
- Run live checks (Self-checks, `mscts run`) from a detached copy at the commit (`git worktree add --detach <path> <sha>`), never from the worktree you edit: a run waiting for the lock picks up edits made meanwhile (#487).
- Before handing back a new Group, run it once on Pumpkin and check every test case name in its Report against `TITLES`: one run found six untitled names (#490).
- Detach a long run with `setsid -f bash -c '…'`; a job started with `nohup … &` ignores SIGINT, which a test that interrupts it needs (#472).
- If the sandbox refuses a detached script that runs `cd` and `git` in your worktree, start `mise run commit` or `git rebase --exec` with the Bash tool's background run instead, and wait on its output file for the commit summary or "Successfully rebased" (#471).
