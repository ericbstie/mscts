---
name: triage
description: Preliminary triage of one mscts issue that carries `needs-triage`, run by a Haiku 5.5 worker before the tech lead assesses it. Finds scope indicators, reproduces a bug, runs a throwaway spike to surface hidden unknowns, and posts one comment in a fixed layout. Use when briefed with "triage #<n>".
---

# triage

You give the tech lead what it needs to assess one issue: how big the
change is, whether the bug is real, and what the issue does not say. You
do not decide anything for the lead and you do not ship anything. Your
only output is one comment on the issue, in the layout under
[Comment](#comment).

## Rules

- Work on exactly the one issue you were given, in your own git
  worktree, never in the main checkout.
- Leave the issue as it is: no label, title, body or assignee changes.
  Removing `needs-triage` is the lead's job.
- Never push, open a PR, run `mise run commit` or commit on `main`.
- Never decide a question the issue leaves open. Write it down under
  **Questions for the lead** and carry on with the rest.
- Use the vocabulary in `CONTEXT.md` exactly.
- Load the function-design skill before you write any code. The
  reproduction test and the spike both follow it, because a worker may
  reuse the test.
- Every claim in the comment names its evidence: a `file:line`, a
  command and its output, or a link. A claim you inferred without
  checking says "inferred".
- Read GitHub with the GitHub MCP tools (load them with ToolSearch;
  repo `ericbstie/mscts`).

## Steps

Do the steps in order. Each one feeds a section of the comment.

### 1. Read

Read these in full:

- the issue and all its comments;
- every issue, PR, ADR, doc page and file the issue names or links,
  even when it reads like background;
- `CONTEXT.md`;
- `docs/PROCESS.md` § Lanes and review levels;
- `docs/RISK.md` § Levels now;
- the handbook of the issue's lane, `docs/roles/<lane>.md`.

Then read the code the issue names, and follow it one call up and one
call down.

### 2. Scope indicators

Fill each row of the table in the comment. Find files with `rg`, not by
guessing, and read the part of each file you list.

- **Files**: every file the change will modify, `src/`, `tests/` and
  `docs/` alike, each with the function or section involved.
- **Suggested scrutiny**: the highest level in `docs/RISK.md` among the
  areas that own those files, one step higher if the change adds new
  concurrency, a new kind of Verdict, or code that later Groups build
  on. `high` stays `high`.
- **Lane**: the `lane:*` whose hard part this is, by the table in
  `docs/PROCESS.md`, or "lead" for platform, tooling and docs. Say
  whether it matches the issue's label.
- **Docs pages**: the pages a user would see change, or "None.".
- **Live tiers**: `reference` if the change touches a codec schema, an
  Adapter, the runner, the Bot or a Group; `candidate` if it changes
  what a Candidate's Report says; otherwise "None.". The scrutiny level
  adds its own runs, so leave those out.
- **Increments**: how many red-green increments (one failing test, the
  code, one commit each) the change needs, and one line naming each.
- **Related issues**: open issues that block this one, that this one
  blocks, or that change the same files. List the open issues with
  `list_issues` (`state: OPEN`, `fields: ["number", "title", "labels"]`),
  then read every one whose title touches the same files or Groups.

### 3. Reproduction

An issue that says the code does something wrong today gets a
reproduction. Any other issue gets "Not applicable: the issue asks for
new behaviour." and you go on to step 4.

1. Create the spike branch from the current `main`:
   `git switch -c triage-<n>-spike origin/main`.
2. Write the smallest unit test that shows the wrong behaviour, in the
   test file a worker would put it in, using the helpers in
   `tests/support/` and the fakes the nearby tests use. Name it after
   the behaviour the issue wants, so it fails today: for example
   `test_a_candidate_that_fails_in_window_one_reports_no_later_window`,
   not `test_issue_334_repro`.
3. Run only that test: `uv run pytest <path>::<name>`.
4. The bug is **reproduced** when the test fails on an assertion that
   shows the wrong behaviour. An import error, a fixture error or a
   timeout is not a reproduction: fix the test and run it again.
5. If no unit test can show it, because the bug only appears against a
   live server, run the one live test that shows it
   (`uv run python scripts/live_lock.py -- uv run pytest -m reference <path>::<name>`).
   Never run a whole live tier.
6. If you cannot reproduce it after three attempts at the test, the
   status is **not reproduced**. Say what you tried and what happened
   instead.

The comment carries the test's code and the last lines of its output.

### 4. Spike

The spike is the quickest change that makes the issue work, written only
to find out what the issue does not say. It is thrown away. Nobody
reviews it and nobody reuses it.

Work on `triage-<n>-spike` (create it as in step 3 if there is no
reproduction). Make the change the issue asks for in the simplest way
you can find. Skip docs, polish and edge cases the issue does not name.
Code that does not exist yet is not a blocker: write the least of it
that the spike needs, and say in the Spike section that it was missing. Where
the issue allows more than one reading, take the narrowest one that
lets its own test pass, carry on, and put the choice under **Questions
for the lead**.

Stop at the first of these and record which one stopped you:

- **Done**: the reproduction test passes, or for new behaviour, one new
  test of the behaviour the issue asks for passes. If the issue asks for
  more than that test shows, the spike is **done, partial**, and the
  comment says what is left.
- **Blocker**: you cannot go on without one of these.
  - A choice between behaviours where no reading of the issue lets its
    own test pass.
  - A protocol or server fact that is not in `docs/research/`, the codec
    schemas, the code or the issue itself. Name the fact. The Spike
    section names any fact you took from the issue as unverified.
  - A change to a public interface, a CONTEXT term or an ADR.
  - A change in a core area that another lane owns (`docs/PROCESS.md`,
    Core areas have one owner).
  - A test that fails for a reason you cannot explain from the code.
- **Budget**: `git diff --shortstat origin/main` shows more than 150
  changed lines, or you have made 20 edits. A change that big is a
  finding in itself.

Then:

1. If the spike stopped at **Done**, run the unit tier once with
   `mise run test` and note every test that now fails.
2. Whatever stopped the spike, save `git diff --stat origin/main` for
   the comment.
3. Discard the spike and the reproduction with it:
   `git switch --discard-changes --detach origin/main`, then
   `git clean -fd`, then `git branch -D triage-<n>-spike`.
   `git status` must show a clean tree.

The Spike section names every surprise the spike met: a caller you
did not expect, a test that pinned the old behaviour, a second place
with the same bug, a fact the issue got wrong, a file outside the ones
you listed in step 2. If the spike changed files that step 2 did not
list, add them to the **Files** row and say so.

### 5. Post

Post the comment with the GitHub MCP tools. If an earlier comment of
yours that starts with `## Preliminary triage` is on the issue, edit
that one instead of posting a new one. Then end with the comment's URL
and nothing else.

## Comment

Use this layout exactly. Keep every heading and every table row, in
this order. A row or section with nothing to report says "None." Keep
each table cell short.

````markdown
## Preliminary triage

<One or two sentences: how big the change is and the main risk the lead
should know about.>

### Scope indicators

| Indicator | Finding |
| --- | --- |
| Files | `src/mscts/<file>.py` (`<function>`); `tests/<file>.py`; `docs/<page>.md` § <section> |
| Suggested scrutiny | `scrutiny::<level>` |
| Lane | `lane:<name>`, <matches or differs from> the label |
| Docs pages | <pages, or None.> |
| Live tiers | <tiers, or None.> |
| Increments | <n>: 1. <increment>; 2. <increment> |
| Related issues | #<n> <how it relates>, or None. |

### Reproduction

**Status:** reproduced, not reproduced, or not applicable.

```python
<the test>
```

```
<the command and the last lines of its output>
```

### Spike

**Stopped:** one of `done`; `done, partial: <what is left>`;
`blocker: <the blocker in one sentence>`; `budget`.

<What the spike changed, and each surprise it met with its evidence.>

```
<git diff --stat origin/main>
```

<The unit tier result after a done spike: "unit tier green", or the
failing tests.>

### Questions for the lead

1. <A choice only the lead or the maintainer can make, with the options
   you saw.>
````
