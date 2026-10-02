# ADR-0009: The docs site is the spec; issues and PRs carry the work

Status: accepted (2026-09-27). Supersedes the queue and "work on `main`"
parts of ADR-0005. Its green-commit rule stands.

## Context

The VitePress site (`docs/`, outside the working notes) now documents
mscts for its users. The maintainer wants to review that site page by
page and define the interface and its wording there. Agents then make the
code match. Before this ADR, `docs/PLAN.md` held "the exact interfaces",
`docs/PROGRESS.md` held the queue, and workers committed to `main` through
the tech lead. That would give three sources of truth for one interface.

## Decision

- **The site is the spec for everything a user sees**: commands, flags,
  output, exit codes, config, Report format, Scenario ids and the Adapter
  authoring interface. `docs/PLAN.md` keeps the internals (module
  interfaces users never touch), goals and milestones.
- **The site always describes the code as it is.** A wording change with
  no behaviour change is committed directly. A change that needs code
  does not go on the site until the code lands. It waits in a GitHub
  issue instead.
- **GitHub issues are the queue.** Each issue is one independent change,
  written from `.github/ISSUE_TEMPLATE/spec.md`. It quotes the target doc
  text verbatim (the Docs delta), states the interface, names the
  acceptance tests, and lists the files and doc sections it owns. One doc
  change may produce several issues. Issues are split so they can be
  worked in parallel, and they declare their dependencies when they
  cannot be.
- **Labels**: `spec` (every spec issue), `ready` (complete and
  unblocked), `needs-decision` (blocked on the maintainer), and `opus` or
  `sonnet` (the recommended worker model).
- **One PR per issue.** A worker owns its issue and its PR. It works on a
  branch named `issue-<n>-<slug>`, applies the Docs delta in the same PR
  as the code, and pushes. The tech lead reviews it against the issue and
  merges it with a rebase, so every commit on `main` still passes
  `mise run check`.
- **Surprises go on the issue.** Anything that changes the issue's scope
  or contradicts its spec is a comment on the issue. If the spec cannot be
  met as written (vanilla behaves differently, or it conflicts with an
  ADR), the worker labels the issue `needs-decision`, comments, and stops
  that part. It never bends the code or the wording to fit.
- **The retrospective stays private to the tech lead.** It goes in the
  Worker report, not on GitHub.
- **Docs are checked.** Wherever a page shows something the code
  produces (help text, command output, Report examples, the glossary),
  a test in the unit tier compares the two. New issues add their examples
  to the checked set.

## Consequences

- `docs/PROGRESS.md` stops being the queue. It keeps Now and the Log and
  points to the open `ready` issues.
- Two issues that edit the same doc section or the same hotspot module
  conflict. The tech lead batches issues whose "Owns" lists are disjoint.
- GitHub access (the GitHub MCP tools) is part of the worker toolchain.
- `git bisect run mise run check` still works across `main`.

## Amendment (2026-10-02): PRs land with a merge commit

The maintainer prefers regular merging. The tech lead still rebases a PR's
branch onto `main` with `git rebase main -x "mise run check"` and pushes
it, then merges the PR with a merge commit instead of a rebase-merge. Every
commit on `main`, the merge commits included, still passes
`mise run check`, so `git bisect run mise run check` keeps working, and
each issue's commits stay together behind their merge. Labels are now
`needs-triage` (not ready: incomplete, or waiting on another issue),
`needs-decision`, `opus` or `sonnet`, a `lane:*` and a `scrutiny::*`
(docs/PROCESS.md, Lanes and review levels). An open issue with neither
`needs-triage` nor `needs-decision` is ready. `spec`, `enabler` and
`ready` are gone.
