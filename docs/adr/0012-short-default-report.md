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

## Amendment (#101, 2026-10-03)

The Report lists every test case, not only the differing ones: one line
per test case per Group, in the order played,
`<✓ or ✗> <group>/<test case> <title>`. A test case passes unless it
differs in gameplay in any repetition. One that differs only in network
traffic passes, as ADR-0007 scores it, and its line ends
`(network traffic only)`.

A Group with no test cases to list (blocked, error, or a Candidate
failure before the comparison) has one ✗ line naming its reasons, such as
`✗ join/basic Not tested: …`, and counts as one test case. A blocked or
failed Group fails. An error Group is listed, marked `!` rather than ✗,
but not scored, because the fault is mscts's or the Reference's.

`No differences.` is gone. Before the total time come the totals and a
score: `35 passed, 5 failed (1 not tested), 1 error (not scored)` and
`Score: 87.5% (35 of 40 test cases pass)`. The score is rounded down, so
only a Run where every scored test case passes shows 100%. The detailed
option adds the values under each line that differs. `report.md` and
`report.json` carry the same lines and totals.

`_LISTED` in `report.py` is the one place that decides which lines are
listed, and `NETWORK_TRAFFIC_ONLY_PASSES` in `compare.py` the one place
that applies ADR-0007's rule. The Report and the check of whether a
prerequisite passed (#221) both read it.

## Amendment (#239, 2026-10-03)

A Comparison that raises is `error`, and left out of the score, only when
the fault is the Reference's data or mscts's. mscts tells the two apart by
comparing the Reference's Transcript with itself. If that does not raise,
the Candidate sent what made the Comparison raise. The Group is then a
`mismatch` led by a `failed` Divergence naming the exception, and its
line reads `Candidate failed: the Comparison failed: …`. If it raises
too, the Group stays an `error`. The candidate tier fails on both, so a
Comparison bug that a Candidate's packets set off still shows.

## Amendment (#262, 2026-10-03)

A Candidate failure of a whole Group (a `failed` Divergence: the Group
raised on the Candidate, the Comparison raised on its data, or the
Candidate was left unusable) fails every test case the Group has in any
repetition, besides the Group's own line. Where the Group was played,
those include each test case of the Reference's play, which the
Comparison of the Reference with itself lists. So a Candidate that
crashes, or sends what the Comparison cannot take, fails at least as
many lines as one that sends every value wrong, and one more. If the
Comparison raises comparing the Reference with itself, the fault is the
Reference's data or mscts's, and the Group is an `error`, however the
Candidate failed. If the Group has no test case in any
repetition, its own line is all that fails. (This first named a
Candidate left unusable as that case; the #266 amendment plays the
Reference there.)

A prerequisite still passes only when each of its test cases passes and
it has no line of its own (#219), so a Group the Candidate failed blocks
the Groups that require it, as before.

## Amendment (#266, 2026-10-04)

A Candidate must never score higher by skipping work than by doing it
wrong. So when the Candidate's side of a Group is not compared, mscts
plays the Reference anyway, and the Candidate fails each test case of
that play, with the Group's own line saying why. This amendment covers
two cases. In both, the Candidate's side is not played:

- The Candidate still has players online from the Group before
  (`Candidate failed: 1 player still online after waiting 2 s: …`).
- A Group earlier in the Run left the Candidate's world frozen
  (`Candidate failed: players/join-seen left its world frozen`). Only the
  Reference is then waited on.

If the Reference fails that play, or the Comparison raises comparing
its play with itself, the Group is an `error`, as in any other Group.
Its Measurements and time are the Reference's play alone. Neither side
is played when the Reference is the side left frozen or unsettled; the
Group is then an `error`.

## Amendment (#284, 2026-10-04)

A Candidate that lacks a command Control sends is no longer `blocked`.
Before, such a Group was one `Not tested: needs /tick` line, and the
Comparison of what the Candidate had played was thrown away. That lost
gameplay differences when the command came last, such as `kill` from
the `blocks/*` undo stack, after every window.

Now it is a Candidate failure like any other, as the #262 amendment
says. It is a `mismatch` led by a `failed` Divergence naming the
command, and its line reads `Candidate failed: missing /tick`. It keeps
what the Comparison found, and the Candidate fails each test case of
the Reference's play. If the Group had already failed, and the command
was missing only while undoing what the Group changed, the line names
that first failure instead. A command missing on the Reference is still
an `error`. `blocked` now means only that a prerequisite did not pass.

## Amendment (#285, 2026-10-04)

A blocked Group was never played, so it was one `Not tested` line. A
Candidate that sent one value of a prerequisite wrong then scored above
one that passed the prerequisite and sent every value of the Groups that
require it wrong.

Now a Group blocked by a prerequisite the Candidate failed is still
played on the Reference, as the #266 amendment does. The prerequisite
failed on the Candidate's side if it is a `mismatch`, or is itself
blocked that way. The Verdict stays `blocked`, and its line still reads
`Not tested: prerequisite status/basic was mismatch`. It lists the test
cases of the Reference's play, and the Candidate fails each of them, in
every repetition, as for a Candidate failure. If that play fails, the
Group is an `error`.

If a prerequisite is an `error`, or was not run, the Group is played on
neither side and its own line is all that fails, as before. That holds
per repetition: a repetition blocked this way lists no test cases and
fails none, even when the Candidate matched the Group in another
repetition (review A). Whether
that line should be an `error` too (audit 2026-10-04, L2) is left open.

## Consequences

Network traffic remains a distinct kind of Divergence and remains
excluded from compliance scores. Only its placement in the terminal
Report changes. The docs explain classification and test case names;
the default Report leaves values to the detailed option.

## Amendment (2026-10-04)

The maintainer asked for a Report that says each thing once.

- The first line names the exact Candidate build tested:
  `Running tests against pumpkin nightly 4426d11 (sha256 b8382a8a…)`. The
  second line from #156 is gone, and so is the Candidate row of the
  detailed header.
- A test case line is `<✓ or ✗> <group>/<test case>`, without its title,
  and still ends `(network traffic only)` when it passed that way.
- The totals and the score share one line:
  `35 passed, 5 failed (1 not tested). (87.5%)`. Errors, which are not
  scored, follow on a line of their own: `1 error (not scored)`. With
  nothing scored, the line has no percentage.
