"""Two-sample tests for statistical Groups (#24, ADR-0006).

Both are written here rather than taken from scipy: each is a few dozen lines of the
standard library, and a statistical Group needs nothing else scipy has.
"""

import bisect
import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

MIN_EXPECTED = 5
"""The fewest samples a chi-square test expects in each category; sparser ones are pooled."""


@dataclass(frozen=True, slots=True)
class Difference:
    """How two samples differ, by a two-sample test.

    Attributes:
        test: The test: `Kolmogorov-Smirnov` or `chi-square`.
        effect: The name of its effect size: `D` or `V` (Cramér's V).
        effect_size: How far apart the two samples are, from 0 (alike) to 1.
        p_value: The chance of a difference at least this large if both samples came from
            one distribution.
    """

    test: str
    effect: str
    effect_size: float
    p_value: float


ALPHA = 0.01
"""The level each sample name of a statistical Group is tested at, after Holm's correction."""

type Sample = float | str
"""One sample: a number, or a category."""

type Summary = dict[str, object]
"""A side's samples of one name, in brief: their count, then their median and quartiles
(`{"samples": 50, "median": 3.2, "quartiles": [1.9, 4.5]}`) or each category's share, to
three decimals (`{"samples": 50, "shares": {"skeleton": 0.6, "zombie": 0.4}}`). A side with
none is `{"samples": 0}`."""


@dataclass(frozen=True, slots=True)
class Decision:
    """Whether a statistical Group's samples of one name differ between the two sides.

    Attributes:
        name: The sample name, e.g. `spawn.distance`.
        rejected: The two sides' samples do not come from one distribution: the test's
            Holm-adjusted p-value is at most `ALPHA`, or there is no test to run because a
            side has no samples of the name, or one side's are numbers and the other's
            categories.
        difference: The test, its effect size and its own p-value; None with no test.
        p_value: The test's p-value after Holm's correction over the Group's tested names;
            None with no test.
        reference: The Reference's samples in brief (`Summary`).
        candidate: The Candidate's samples in brief.
    """

    name: str
    rejected: bool
    difference: Difference | None
    p_value: float | None
    reference: Summary
    candidate: Summary


def decide(
    reference: Mapping[str, Sequence[Sample]], candidate: Mapping[str, Sequence[Sample]]
) -> tuple[Decision, ...]:
    """Each sample name either side has, in name order: do the two sides' samples differ?

    Numbers are tested with `kolmogorov_smirnov`, categories with `chi_square`, and the
    p-values of the names tested are corrected together (`holm`), so a Group with several
    names still rejects one by chance at most `ALPHA` of the time. Each name's samples on a
    side are all numbers or all categories, as `GroupContext.sample` keeps them.
    """
    names = sorted({*reference, *candidate})
    differences = {
        name: difference
        for name in names
        if (difference := _tested(reference.get(name, ()), candidate.get(name, ()))) is not None
    }
    adjusted = dict(zip(differences, holm([d.p_value for d in differences.values()]), strict=True))
    return tuple(
        Decision(
            name=name,
            rejected=name not in adjusted or adjusted[name] <= ALPHA,
            difference=differences.get(name),
            p_value=adjusted.get(name),
            reference=summary(reference.get(name, ())),
            candidate=summary(candidate.get(name, ())),
        )
        for name in names
    )


def holm(p_values: Sequence[float]) -> list[float]:
    """The Holm-Bonferroni adjusted p-values of `p_values`, in the same order.

    The k-th smallest of m is multiplied by m - k + 1, raised to the one before it if it
    is smaller, and capped at 1. A name rejects when its adjusted p-value is at most `ALPHA`.
    """
    order = sorted(range(len(p_values)), key=lambda index: p_values[index])
    adjusted = [1.0] * len(p_values)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (len(p_values) - rank) * p_values[index]))
        adjusted[index] = running
    return adjusted


def summary(samples: Sequence[Sample]) -> Summary:
    """`samples` in brief (`Summary`): their median and quartiles, or each category's share."""
    if not samples:
        return {"samples": 0}
    if all(isinstance(sample, str) for sample in samples):
        counts = Counter(samples)
        shares = {name: round(counts[name] / len(samples), 3) for name in sorted(counts)}
        return {"samples": len(samples), "shares": shares}
    numbers = [float(sample) for sample in samples]
    lower, median, upper = statistics.quantiles(numbers, n=4, method="inclusive")
    return {"samples": len(samples), "median": median, "quartiles": [lower, upper]}


def _tested(reference: Sequence[Sample], candidate: Sequence[Sample]) -> Difference | None:
    """The two-sample test of one name's samples, or None if they cannot be tested.

    They cannot when a side has none, or one side's are numbers and the other's categories.
    """
    if not reference or not candidate:
        return None
    words = [isinstance(side[0], str) for side in (reference, candidate)]
    if words == [True, True]:
        return chi_square([str(sample) for sample in reference], [str(s) for s in candidate])
    if words == [False, False]:
        return kolmogorov_smirnov(_numbers(reference), _numbers(candidate))
    return None


def _numbers(samples: Sequence[Sample]) -> list[float]:
    return [sample for sample in samples if not isinstance(sample, str)]


def kolmogorov_smirnov(reference: Sequence[float], candidate: Sequence[float]) -> Difference:
    """The two-sample Kolmogorov-Smirnov test of two samples of numbers.

    D is the largest gap between the two samples' cumulative shares. The p-value is exact
    (Hodges' count of the orderings of the two samples that reach a gap that large). It
    assumes no value is repeated; repeated values make it larger than the true one, so the
    test rejects less often, never more.

    Raises:
        ValueError: A side has no samples.
    """
    _require_samples(reference, candidate)
    n, m = len(reference), len(candidate)
    gap = _largest_gap(sorted(reference), sorted(candidate))
    return Difference(
        test="Kolmogorov-Smirnov",
        effect="D",
        effect_size=gap / (n * m),
        p_value=_reaching(gap, n, m),
    )


def chi_square(reference: Sequence[str], candidate: Sequence[str]) -> Difference:
    """The chi-square test of homogeneity of two samples of categories.

    Categories under `MIN_EXPECTED` expected samples on a side are pooled first (`pooled`).
    One category left means no difference can be shown: V 0, p-value 1.

    Raises:
        ValueError: A side has no samples.
    """
    _require_samples(reference, candidate)
    ours, theirs = Counter(reference), Counter(candidate)
    columns = pooled([(ours[name], theirs[name]) for name in sorted(ours | theirs)])
    if len(columns) < 2:  # noqa: PLR2004 - a test of homogeneity needs two categories
        return Difference(test="chi-square", effect="V", effect_size=0.0, p_value=1.0)
    statistic = _pearson(columns)
    total = len(reference) + len(candidate)
    return Difference(
        test="chi-square",
        effect="V",
        effect_size=math.sqrt(statistic / total),
        p_value=chi_square_survival(statistic, len(columns) - 1),
    )


def pooled(columns: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """`columns`, the two sides' counts per category, with the sparse categories pooled.

    A category is sparse when the side with fewer samples expects fewer than `MIN_EXPECTED`
    of it. The two smallest categories are merged until none is sparse, or one is left.
    """
    fewer = min(sum(column[0] for column in columns), sum(column[1] for column in columns))
    total = sum(map(sum, columns))
    left: list[tuple[int, int]] = sorted(columns, key=sum)
    while len(left) > 1 and fewer * sum(left[0]) < MIN_EXPECTED * total:
        merged = (left[0][0] + left[1][0], left[0][1] + left[1][1])
        left = sorted([merged, *left[2:]], key=sum)
    return left


def chi_square_survival(statistic: float, df: int) -> float:
    """The chance that a chi-square variable with `df` degrees of freedom is at least `statistic`.

    In closed form, as integer degrees of freedom allow: a finite sum of the Poisson terms
    for an even `df`, and the normal tail plus a finite sum for an odd one.

    Raises:
        ValueError: `df` is less than 1.
    """
    if df < 1:
        msg = f"a chi-square distribution has at least 1 degree of freedom, not {df}"
        raise ValueError(msg)
    half = statistic / 2
    if df % 2 == 0:
        term, total = math.exp(-half), 0.0
        for i in range(df // 2):
            total += term
            term *= half / (i + 1)
        return min(1.0, total)
    total = math.erfc(math.sqrt(half))
    term = math.sqrt(2 * statistic / math.pi) * math.exp(-half)
    for i in range(1, (df + 1) // 2):
        total += term
        term *= statistic / (2 * i + 1)
    return min(1.0, total)


def _require_samples(reference: Sequence[object], candidate: Sequence[object]) -> None:
    for side, samples in (("Reference", reference), ("Candidate", candidate)):
        if not samples:
            msg = f"the {side} has no samples to test"
            raise ValueError(msg)


def _largest_gap(reference: Sequence[float], candidate: Sequence[float]) -> int:
    """The largest gap between the sorted samples' cumulative shares, times n * m."""
    n, m = len(reference), len(candidate)
    return max(
        abs(bisect.bisect_right(reference, value) * m - bisect.bisect_right(candidate, value) * n)
        for value in (*reference, *candidate)
    )


def _reaching(gap: int, n: int, m: int) -> float:
    """The share of the orderings of n and m values whose cumulative gap reaches `gap` / (n m).

    An ordering is a lattice path from (0, 0) to (n, m); it stays inside while every point
    (i, j) has |i m - j n| < gap. A gap of 0 is reached by every ordering.
    """
    if gap == 0:
        return 1.0
    inside = [1] + [0] * m  # the paths to (0, j) that stayed inside
    for j in range(1, m + 1):
        inside[j] = inside[j - 1] if j * n < gap else 0
    for i in range(1, n + 1):
        inside[0] = inside[0] if i * m < gap else 0
        for j in range(1, m + 1):
            inside[j] = inside[j] + inside[j - 1] if abs(i * m - j * n) < gap else 0
    total = math.comb(n + m, n)
    return float(Fraction(total - inside[m], total))


def _pearson(columns: Sequence[tuple[int, int]]) -> float:
    """Pearson's chi-square statistic of a two-row table, one (row 0, row 1) count per column."""
    rows = (sum(column[0] for column in columns), sum(column[1] for column in columns))
    total = sum(rows)
    expected = [[row * sum(column) / total for row in rows] for column in columns]
    return sum(
        (observed - mean) ** 2 / mean
        for column, means in zip(columns, expected, strict=True)
        for observed, mean in zip(column, means, strict=True)
    )
