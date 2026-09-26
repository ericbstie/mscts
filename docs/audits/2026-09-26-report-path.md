# Audit AC: the Report path (`mscts run`)

Date: 2026-09-26. Base: `main` at `440f3a8`, plus AC's compare commits.
Auditor: worker AC (opus), read-only.

Scope: `src/mscts/measure.py`, `src/mscts/report.py`, `run.run_results`,
`run.judge`, `run.blocked`, and the `mscts run` path in `src/mscts/cli.py`.
Method: read each against PLAN, ADR-0007 and the live Report of
`mscts run --candidate pumpkin`; checked `stats`' nearest rank
(`math.ceil(0.95 * n)`) against exact integer arithmetic for every
n ≤ 100 000 (no difference).

## Summary

No high finding: no path makes the Report say "no differences" while a
Divergence, a `blocked` or an `error` Verdict exists (`report._state` ranks
error, observable, wire-only, blocked before "identical", and the summary
says "No differences" only when every Scenario is identical), no
Divergence is dropped by grouping (observable ones are deduplicated per
Scenario by their full repr, with an "in N of M runs" count; wire-only ones
per packet with a count), median and p95 are right, and Instances are
stopped by `run_results`' exit stack on every path (the runner's `running`
stops its process on error and on cancellation during readiness).

The two Pumpkin status Divergences the brief named were misclassified as
observable; they are fixed in this brief (research note, `compare.py`).

## Findings

**MD1 (medium) — a wire-only difference in a prerequisite blocks its
dependents.** `src/mscts/run.py:265`: `blocked` requires every prerequisite
to be `match`. A Verdict with only wire-only Divergences is `mismatch`
(ADR-0007), so a Scenario that requires, say, `status/basic` is `blocked`
on Pumpkin today, although nothing a player could notice differs. No
registered Scenario has `requires` yet (the lead removed status/ping's), so
nothing is hidden now; the join Scenario will be. Proposal: block only on
a prerequisite with observable Divergences, error or blocked (a PLAN
decision, not a bug fix).

**L1 (low) — Timings include repetitions the Report calls "not measured".**
`src/mscts/run.py:459` keeps each side's completed spans even when the
Verdict is `error` (the Reference or the harness failed mid-Scenario), yet
`src/mscts/report.py:254` says "Not measured where it was not played" for
every Scenario with a blocked **or error** repetition. Failure scenario:
the Reference times out once in five; its four good `status.rtt` values
plus any partial span are in the median, and the line claims nothing was
measured. Proposal: say "blocked" Scenarios measured nothing and "error"
repetitions may have measured part of the Scenario, or drop the spans of
error repetitions.

**L2 (low) — a Scenario that errs once reads only as "could not be run".**
`src/mscts/report.py:109`: one `error` repetition outranks observable
differences in the others, so the summary counts it under "could not be
run", not "different". The differences are still listed under "Differences
a player would notice", so nothing is hidden, but the summary line
under-counts. Proposal: count it in both, or say "different (1 run could
not be judged)".

**L3 (low) — "p95" of fewer than 20 values is the maximum.**
`src/mscts/measure.py:80` is a correct nearest-rank p95, but with the
default `--repeat 5` it is always the largest value, and for
`instance.startup` (n = 1) it equals the median. A reader may take it for a
tail estimate. Proposal: show "max" when n < 20, or print n beside each
statistic (the table has a shared `n` column).

**L4 (low) — the wire-only examples do not say how many are not shown.**
`src/mscts/report.py:198` shows at most `WIRE_EXAMPLES` (3). The live
Report says "4 values differ on the wire, e.g." and lists three; the
fourth (`players.sample`, absent vs `[]`) is invisible. The count is
right, so nothing is miscounted. Proposal: "… and 1 more".

**L5 (low) — only observable differences are called unsettled.**
`src/mscts/report.py:221` flags a Scenario "different in X of N runs" for
observable Divergences only. A wire-only Divergence present in some
repetitions only (say, a Candidate's non-deterministic key order) is not
flagged, though it is listed. Proposal: flag any Divergence that varies
between repetitions, so a nondeterministic Candidate shows up.

**L6 (low) — `mscts run` exits 0 whatever it found.** `src/mscts/cli.py:216`.
A CI job cannot fail on observable differences or `error` Verdicts without
parsing the text. Proposal: an exit code (or a flag) for "observable
differences" and "could not be judged", decided with `--out`.

**L7 (low) — a RunnerError loses the Report of what already ran.**
`src/mscts/cli.py:208`: an Instance that fails to launch for a later
ServerSpec raises out of `run_results`, and the Verdicts of the Scenarios
already played are not rendered. Today every Scenario shares one ServerSpec,
so it cannot happen yet. Proposal: when Scenarios with other ServerSpecs
land, report what ran and mark the rest `error`.

**L8 (low) — the `failed` line does not name the Bot.**
`src/mscts/report.py:330` renders a `failed` Divergence as "the Candidate
failed: …" without `divergence.bot`, which `judge` now fills. With several
Bots the reader cannot tell which connection failed. Proposal: add the Bot
name when it is not empty.

Not fixed here: none is high, and the brief allows fixing only high ones.
