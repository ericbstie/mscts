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

- Every commit passes `mise run check`. Commit only with
  `mise run commit -- -F /abs/msg.txt`, and push after each commit. Never
  `git stash`. The check includes `plan`: every new public top-level name in
  src/ needs a docs/PLAN.md entry in the same commit.
- Tests red first (pin tests of recorded payloads and mutant killers
  excepted: say so in the commit message). A mutation sweep with
  `scripts/mutate.py --batch spec.json --jobs 4 -- <tests>` (red-green,
  Known traps), output redirected to a log in your scratch dir. Name the
  narrowest test selection that kills the mutants, and pass `--timeout 300`.
- Repeat a selection with
  `uv run scripts/repeat.py --times N [--stress] -- <pytest args>` (one
  line per run, the union of failures). Never hand-roll a loop. Use
  `--stress` only when your brief or issue asks: it slows every other
  agent's tiers on this host.
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
- Live-tier mise tasks share `<cache>/live-tier.lock` (#138). A second
  waits for the holder; `MSCTS_LIVE_LOCK=0` bypasses it on a machine known
  to have enough capacity. The unit tier takes no lock.
- Rebase onto main only before opening the PR
  (`git rebase main --exec "mise run check"`), and report commit hashes
  only in the final report. A timing claim compares clean main and your
  branch back-to-back on this host (median of three), never a lone number.
  Before deleting a shared helper, grep origin/main for its users.
- Commit messages and the PR body end with the attribution lines your own
  session's system reminder gives. Name no model anywhere else. One issue
  comment at most, for decisions.
- Meet the scrutiny level (the issue's `scrutiny::*` label) (PROCESS, Lanes and
  review levels) before you hand back the PR.
- End each issue with the Worker report exactly as docs/PROCESS.md
  specifies, with a thorough Retrospective, and the lines you propose for
  your lane's handbook. State your worktree path, branch and PR URL.
