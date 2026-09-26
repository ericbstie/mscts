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
   A *pin* test (one that locks down behaviour that already exists, such
   as a golden file or an idempotence check) may be green at once. Prove
   it bites with `scripts/mutate.py` (see Known traps), and say so in the
   report.
3. **Green.** Write the minimum code. Do not add code for a later
   increment, and do not add options nobody asked for.
4. **Refactor** while green, if the code now reads worse than the code
   around it.
5. **Check.** `mise run check`. If you touched anything server-facing
   (codec schemas, adapters, runner, Bot, Scenarios), also run
   `mise run test:reference`.
6. **Commit** the test and the code together. Write the message to a file
   (`git commit -F /abs/msg.txt`, never a heredoc), then commit through
   **`mise run commit -- -F /abs/msg.txt`: THE way to commit in this
   repo.** It runs `mise run check` itself, never through a pipe (it
   captures the check's own combined output to a temp file and reads the
   check subprocess's own exit code directly, then prints the tail), and
   runs `git commit -F /abs/msg.txt` only when that exit code is 0; on a
   red check it prints the failing part and exits with the check's own
   code without ever calling `git commit`
   (`scripts/commit_green.py`, `tests/tooling/test_commit_green.py`).
   Never run `mise run check` yourself and separately pipe or chain its
   result into a `git commit` call. Use `<area>: <imperative summary>`
   for the subject line, where area is one of `codec`, `net`, `bot`,
   `transcript`, `target`, `spec`, `adapter/<name>`, `runner`, `scenario`,
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
- Unit tests are **hermetic**: no external network, no Java, no Candidate
  binary. Localhost sockets and short helper processes (well under 1 s,
  always cleaned up) are allowed. Anything needing vanilla or a Candidate
  goes in a tier: `@pytest.mark.reference` or `@pytest.mark.candidate`.

## Known traps

- The Write/Edit tools turn `\uXXXX` in file content into the literal
  character. For a literal backslash-u in Python source, write `"\\u00E9"`
  (non-raw) and check it with `grep … | cat -A`. For test inputs, prefer
  `\xNN` or `\U0001….`.
- ty's `unsound-return-statement` rejects returning an `Any` (e.g. urllib's
  `response.read()`, an `re.Match` group). Narrow it with `isinstance` and
  raise, or wrap it (`str(match["x"])`), since S101 forbids `assert` in
  `src/`.
- Mutate with `python3 scripts/mutate.py <file> <old> <new> -- <pytest args>`:
  it asserts `<old>` occurs exactly once, applies it, runs `uv run pytest
  <pytest args>` under a timeout (default 60 s), and always restores
  `<file>` from its own backup (not git), verified by sha256 — on a pass, a
  fail, a timeout or Ctrl-C, so it is safe to run with uncommitted work in
  that file. Never hand-edit a mutation with `sed` or an editor, and never
  undo one with `git checkout <file>`: a loose `sed` pattern once hit two
  lines and hung pytest with no restore, and `git checkout` wipes
  uncommitted work in the file too.
  - **Verdicts, not just an exit code.** KILLED (tool exit 0) means pytest
    actually ran the selection and at least one test FAILED (pytest exit
    1) — the only outcome that proves the tests bite. SURVIVED (tool exit
    1) means pytest ran and every test passed (pytest exit 0): strengthen
    the tests. INVALID (tool exit 3) covers everything else — a timeout,
    or pytest exit 2 (interrupted), 3 (internal error), 4 (usage error,
    e.g. a mistyped path) or 5 (no tests collected) — and is never a
    kill, however the pytest process happened to exit: MD6
    (docs/audits/2026-09-26-foundation.md) found a mistyped test path
    counted as KILLED, which made "the tests bite" claims vacuous. Read
    the printed detail, not just the verdict word.
  - **A green baseline first.** Before mutating, `mutate.py` runs the same
    pytest selection once, unmutated; if that is not green it reports
    INVALID ("the selection is not green before mutating") and never
    touches the file — a mutation can only be judged against tests that
    were passing already. Pass `--skip-baseline` only when you already
    know the selection is green (batch mode uses this to check once for
    the whole batch instead of once per mutation).
  - **Batch mode** runs many mutations without touching this worktree:
    `python3 scripts/mutate.py --batch <spec.json> [--jobs N] --
    <pytest args>`, where `<spec.json>` is a JSON list of `{file, old,
    new, [id]}` objects. Each mutation runs in its own throwaway copy of
    the tracked working tree (so the whole batch's baseline runs once,
    not once per mutation), optionally `--jobs N` at a time. Prints one
    `<id> <VERDICT>: <detail>` line per mutation and a summary, and exits
    non-zero if any mutation SURVIVED or was INVALID. Use it for an
    audit's mutation sweep instead of a hand-rolled loop over
    `mutate.py`.
- Flake-hunt with `python3 scripts/repeat.py [--times N] [--stress]
  [--stress-workers N] -- <pytest args>`: runs `uv run pytest <pytest
  args>` `N` times (default 1) and reports how many runs passed, how many
  failed, and the union of failing test ids across every run. `--stress`
  spawns `--stress-workers` busy-loop processes (default `os.cpu_count()`,
  i.e. `nproc`) to load every CPU for the duration, and always kills them
  afterwards — on a normal return, an exception, or Ctrl-C — with the
  leak-guard pattern (a per-invocation token, swept from `/proc`). Exits
  non-zero if any run failed. Run the whole unit tier through it before
  trusting a readiness, timing or process change beyond the "run it 20
  times" rule (below): `python3 scripts/repeat.py --times 20 --stress --
  -m 'not reference and not candidate and not statistical' -n auto`.
- To silence one line for both ruff and bandit, write
  `# noqa: S603  # nosec B603`: two separate `#` tokens, noqa first. A
  combined comment satisfies only one tool. Keep a nosec to its rule ids,
  since bandit warns about every other word after it.
- A session-scoped async fixture (such as the shared Reference) needs
  `@pytest_asyncio.fixture(scope="session", loop_scope="session")`, and
  every test using it needs `@pytest.mark.asyncio(loop_scope="session")`.
  Both sides must agree. Asyncio objects are bound to the loop that made
  them.
- Helpers: `from tests.net.fakes import …` works under importlib mode,
  because pytest synthesizes the namespace packages. `tests/support/`
  (`import support`) is for plain helpers that need no collection order.
- Lint on new scripts: a shebang needs `chmod +x` (EXE001); a `\t` in a
  docstring needs `r"""` (D301); alias `collections.abc.Set` as
  `AbstractSet` (PYI025); bandit S105 fires on a constant *named* like
  `_TOKEN`, even when it holds an env-var name.
- ty and recursive JSON-like values: declare one recursive alias
  (`type _Value = bool | int | … | list[_Value] | dict[str, _Value] | None`)
  and narrow with `isinstance`. Python 3.13 evaluates annotations
  eagerly, so define aliases above their first use.
- A branch that looks like an optimization (a prefix/suffix trim, a fast
  path) must be proven equivalent by an exhaustive small-domain check, or
  pinned by a test. One silently changed results.
- `uv run` from a copy of the repo ignores `VIRTUAL_ENV`. Use
  `UV_PROJECT_ENVIRONMENT=<venv>` with `--no-sync`. The editable install's
  `.pth` names the original checkout, so a copy needs
  `PYTHONPATH=<copy>/src` ahead of it. `tempfile.mkdtemp` already creates
  its directory.
- `-k` does not match hyphenated parametrize ids. Check with
  `--collect-only -q` first.
- Readiness, timing or process changes: run the touched test files 20
  times before committing.
- ty: `return frozenset()` infers `frozenset[Unknown]`, so annotate the
  empty value. Pass a deliberately wrong type in a test with
  `cast("str", x)`.
- Tests that scan `/proc` must wait for their helper to exec, and ignore
  processes they did not start. Threaded or async fakes must wait for a
  "client connected" cue before acting. Poll through an `asyncio.Event`
  the fake sets, not a sleep loop. Split a long fake handler into step
  methods early (PLR0915).
- `scripts/strays.py <pattern>` alone can match another worker's own live
  process running the same argv (e.g. two workers' vanilla Instances both
  named `server.jar`). Narrow it: `--token NAME=value` only matches a
  process whose `/proc/<pid>/environ` holds that exact entry (the leak
  guard's per-test token is one), and `--cwd PREFIX` only one whose
  `/proc/<pid>/cwd` resolves under `PREFIX` (your worktree or a test's
  tmp workdir). Both combine with `<pattern>`, and with each other, by
  AND.
- Async functions take `timeout_s`, never `timeout` (ruff ASYNC109).
- At most 5 parameters, keyword-only included (PLR0913). Derive values
  rather than passing them. Never add a `noqa` before ruff has actually
  flagged the line.
- In tests, always open Connections and Bots through a closing context
  manager. A leaked socket is garbage-collected during a *later* test, and
  `filterwarnings=error` then fails the wrong test.
- Monkeypatch instances, not library classes. Patching an asyncio class
  also hit the fake server and hung the suite.
- Lint shapes that pass: parametrize many arguments with one frozen case
  dataclass (PLR0913/PLR0917); call a single local coroutine or function
  inside `pytest.raises` (PT012); collect values into a list inside the
  block, rather than using an `as` name after a raising block (ty
  possibly-unresolved); write polling as
  `while True: if await probe(): return …; await asyncio.sleep(…)`
  (ASYNC110).
- JSON under ty: `json.loads` returns `Any`, and a value narrowed by
  `isinstance(x, dict)` is `Top[dict[Unknown, Unknown]]`, which cannot be
  indexed. Recipe: annotate as `object`, narrow with `isinstance`, iterate
  `.items()`, and rebuild a typed `dict[str, object]`.
- `respect-type-ignore-comments = false` means `# type: ignore` does
  nothing. A frozen-dataclass test must use `setattr(obj, name, v)` with a
  non-literal name.
- A new member on a `Protocol` (e.g. `Adapter`) makes ty reject every
  implementer at once, so change all implementers in the same commit, and
  count them in the brief's line budget.
- `mutate.py` batch mode copies tracked files only: `git add` a new test
  file before a batch run, or it reports INVALID "file not found".
- More lint/type shapes: RUF043 wants a raw, escaped `match=` pattern
  (`r"…26\.3"`); a `match=` containing `[[` warns (FutureWarning, an error
  here), so escape it; ty wants `@override` on `__str__`; ty rejects
  `**dict[str, object]` into a dataclass, so use `dataclasses.replace`;
  argparse `set_defaults(run=…)` yields `Any`, so dispatch through a typed
  table.

- Parametrize ids must be deterministic: pytest-xdist workers collect
  separately and refuse to run if their ids differ. Pass explicit `ids=`
  for bytes or generated values, and never let fixture bytes depend on the
  clock (zip entries: `zipfile.ZipInfo(name, FIXED_DATE)`).
- The run fakes' `serve` re-raises `from None`, which overwrites
  `__cause__`: catch inside the `serve` body when a test inspects the
  cause.
- Reword or fix up your own unpushed commits without an editor:
  `git commit --fixup=<sha>`, then `GIT_SEQUENCE_EDITOR=true git rebase -i
  --autosquash <base>`.

- Long expected messages: bind a multi-line string to a name first, and
  never put an implicit concatenation inside `[...]` (ruff format joins it,
  then ISC004 fires).

- A deliberately wrong type in a test: ty 0.0.84 rejects `cast("int", 1.0)`
  (disjoint types), even through an `object`-typed constant. Use
  `cast("T", _untyped(v))` with `def _untyped(v: object) -> object`.
- Writing a server's file format: pin the writer byte for byte against a
  file the Reference itself wrote.

- Shell from a worktree: use `uv run --directory /abs/worktree …` and
  `mise run --cd /abs/worktree …` instead of `cd … && …`, and Write/Edit
  instead of a heredoc append (`cat >> f <<EOF` was refused on its own).

## When stuck

- If a test fails in a way you don't understand, shrink the reproduction
  before changing code.
- If a regression appeared at some point in history, run
  `git bisect start <bad> <good>` then
  `git bisect run uv run pytest <test>`.
- If you are going in circles, go back to the last green commit
  (`git reset --hard HEAD` in your own worktree) and take a smaller step.
  Never use `git stash`, not even for a quick throwaway experiment: all
  worktrees share one stash stack, so you could pop another worker's
  changes. Flip the line with Edit, then flip it back.
