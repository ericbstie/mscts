# ADR-0012: the default Report is a short list of differences

Status: accepted. Reverses ADR-0007's separate network traffic section.

## Context

The default terminal Report's header, summary, sections and timing table
made differences harder to scan. The maintainer asked for one first line,
a plain list of differences and the total Run time (#9).

## Decision

The default Report starts with `Running tests against <adapter name>`.
It lists each differing test case once, using its title when known and
always keeping its name. Gameplay and network traffic differences use
the same list. If none differed and no Group failed or was skipped, it
says `No differences.`.

After the test cases, each blocked, error or failed Group is named with
its reason. Nothing untested is hidden. The final line gives the total
elapsed time, including starting and stopping Instances, in seconds.

The detailed option in #10 adds the Reference, Candidate's installed
version, Target and repetitions, the two values for each difference,
and time per Group. It does not restore Notes, the legend or the
per-measurement timing table.

## Amendment (#156, 2026-10-03)

The default Report's second line names the exact Candidate build tested:
`Candidate: <adapter name> <build> (sha256 <first 8>…)`, for example
`Candidate: pumpkin nightly 4426d11 (sha256 b8382a8a…)`. The detailed
option shows it in its own header instead, next to the Reference.

## Consequences

Network traffic remains a distinct kind of Divergence and remains
excluded from compliance scores. Only its placement in the terminal
Report changes. The docs explain classification and test case names;
the default Report leaves values to the detailed option.
