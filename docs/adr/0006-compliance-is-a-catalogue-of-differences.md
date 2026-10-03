# ADR-0006: Compliance is a catalogue of differences, including randomness and glitches

Status: accepted (2026-09-26)

## Context

The product goal is concrete. Run the suite against a Candidate and get an
exact list of every way it behaves differently from vanilla. A difference
is not necessarily a defect, since a Candidate may deviate on purpose, but
it must be surfaced precisely. The mechanics that matter most include:

- redstone timing;
- spawn rates and positions;
- vanilla's bugs and glitches (headless pistons breaking bedrock, ender
  pearls phasing through the nether roof).

Two things in the plan worked against this:

- Masks were meant to hide "nondeterministic" fields, spawn position
  among them. That would have hidden exactly the random mechanics we
  want to measure.
- Comparison worked on wall-clock-stamped packet streams, which cannot
  tell whether something happened on tick 4 or tick 5.

## Decision

1. **The Report is a raw catalogue of Divergences, grouped by mechanic**
   (protocol, world/blocks, redstone, entities/spawning, physics/movement,
   vanilla bugs/glitches). Each entry names its reproducible Scenario.
   There are **no declared or expected deviations**. Candidates cannot
   annotate or exclude differences; interpretation is left to the reader.
   A list of accepted deviations would let a Candidate decide which of its
   differences count.
2. **Masks are only for identifiers with no gameplay meaning**, such as
   entity ids, keep-alive ids and teleport ids. Anything a player could
   observe as gameplay is never masked. If it varies between vanilla runs,
   it is judged statistically, per item 3.
3. **There are three kinds of Scenario:**
   - **exact**: deterministic protocol or world behaviour, diffed packet
     by packet;
   - **tick-exact**: deterministic mechanics such as redstone and glitches,
     observed tick by tick. The Scenario freezes and steps the world (for
     example `/tick freeze` / `/tick step`) and anchors observations to
     world age, not wall time;
   - **statistical**: random mechanics such as spawn position, mob spawn
     rates, loot and random ticks. Each runs N times on each server, and
     the Candidate's samples are tested against the Reference's
     distribution with a stated test and confidence level. The Verdict
     reports the effect size, not just pass/fail.
4. **Statistical Scenarios run in their own, opt-in tier.** They are never
   part of the unit tier or the default Run. They get a dev marker
   (`statistical`) and a separate Run profile, so the fast loop stays
   fast.
5. **Fixtures use commands only for now.** The Operator Bot sends vanilla
   command syntax (`/setblock`, `/fill`, `/tick`, `/gamerule`, …). If a
   Candidate lacks a command a Scenario needs, that Scenario's Verdict is
   `blocked`, naming the command. Reports count these blocks per command.
   If blocks from missing commands turn out to be common, we will add a
   fallback where a Bot builds Fixtures by placing blocks itself.
6. **Known vanilla bugs and glitches are first-class Scenarios.** A
   Candidate that "fixes" one shows up as a Divergence, like any other.

## Consequences

- Wherever PLAN or PROGRESS said "pin or mask" for spawn position, that is
  replaced. A statistical `spawn/join-position` Scenario measures the
  distribution. Exact Scenarios that need a fixed position set one through
  Fixtures instead (`/setworldspawn`, `/tp`, a spawn-radius gamerule).
- The Self-check applies per kind: exact and tick-exact Scenarios must
  `match` Reference against Reference. A statistical Scenario's Self-check
  must not reject the null hypothesis at the chosen confidence level. This
  guards against a wrongly calibrated test.
- Tick-exact Scenarios need new infrastructure: tick-indexed observation,
  world-age anchoring, and freeze/step control. Their first brief must
  verify in `/tick` research that vanilla's tick freezing is observable
  over the protocol (`ticking_state`, `ticking_step`, `set_time`).
- A Candidate without `/tick` is `blocked` for every tick-exact Scenario
  until the Bot-built fallback exists.
- Masks need a gameplay-relevance justification in their `reason`.
  Reviews and audits reject a Mask that hides player-observable behaviour.

## Amendment (2026-10-03, #254): report.json keeps 20 Divergences of a test case

The Report lists every test case that differs, and the printed Report is not
cut short. `report.json` also keeps each Divergence with both values, but not
without limit: a default Run against Pumpkin wrote an 88 MB file. Five
repetitions held 35,423 Divergences each, 33,579 of them the elements of one
tag list that Pumpkin orders differently from vanilla.

So a Verdict in `report.json` keeps the first 20 Divergences of each test
case, and `omitted` counts the others. A Divergence past the 20 stays if it is
the first of its test case with its kind, observability and kind of value, so
the lines and the score that follow from the Divergences come out the same. A
Group's own differences, which have no test case, are never left out. Nothing
about which test cases differ, or how, is lost; only repeats of the same
difference in one test case.

One Divergence for each shifted list element is itself a finding, and the
Comparison may change it (a separate issue).
