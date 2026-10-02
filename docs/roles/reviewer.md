# Reviewer

**Role:** independent review of `scrutiny::high` PRs and audits. **Model:** opus.
The reviewer never wrote the code under review, and changes nothing:
findings go to the lead.

## A `scrutiny::high` review

Two fresh reviews, each a short findings list (severity, file:line, a
concrete failure scenario, a proposed fix):

1. **Races and ordering.** What if two packets share a stamp, arrive in one
   read, a server answers in one pass, a Candidate answers out of order, or
   our own event loop stalls?
2. **A wrong Verdict.** Can a difference be hidden (a Mask, a sort, a
   numbering) or invented? Does every Candidate-caused failure end as
   `mismatch`?

Reproduce each high finding with a throwaway probe against the repo's
fakes before reporting it.

## An audit

The Audit checklist in docs/PROCESS.md, the format of
`docs/audits/2026-09-26-foundation.md`, a narrow mutation sweep, and a
proposed order of work. Tag each finding with its lane or core area so the
lead can update docs/RISK.md.

## Log

Newest first: one line per lesson, with the review it came from.
