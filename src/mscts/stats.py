"""Two-sample tests for statistical Groups (#24, ADR-0006).

Both are written here rather than taken from scipy: each is a few dozen lines of the
standard library, and a statistical Group needs nothing else scipy has.
"""

import bisect
import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
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


@dataclass(frozen=True, slots=True)
class Numbers:
    """One name's samples on one server, all numbers, in the order recorded."""

    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class Categories:
    """One name's samples on one server, all categories, in the order recorded."""

    values: tuple[str, ...]


type Series = Numbers | Categories
"""One name's samples on one server: numbers or categories, never both."""


class SampleLog:
    """What a statistical Group records on one server over its plays, by sample name."""

    def __init__(self) -> None:
        """Start empty."""
        self._values: dict[str, list[Sample]] = {}

    def add(self, name: str, value: Sample) -> None:
        """Record `value`, a number or a category, as a sample called `name`.

        Raises:
            ValueError: `name` is empty; or `value` is a number that is not finite; or
                `name` holds numbers and `value` is a category, or the other way round.
            TypeError: `value` is neither a number (int or float, not bool) nor a category
                (str).
        """
        if not name:
            msg = "a sample needs a name, e.g. 'spawn.distance'"
            raise ValueError(msg)
        if isinstance(value, bool) or not isinstance(value, int | float | str):
            msg = f"a sample is a number or a category (a str), not {type(value).__name__}"
            raise TypeError(msg)
        if not isinstance(value, str) and not math.isfinite(value):
            msg = f"a number sample is finite, not {value}"
            raise ValueError(msg)
        earlier = self._values.setdefault(name, [])
        if earlier and isinstance(earlier[0], str) != isinstance(value, str):
            held = "categories" if isinstance(earlier[0], str) else "numbers"
            msg = (
                f"sample {name!r} holds {held}, so {value!r} cannot join it: a name holds "
                f"numbers or categories, never both"
            )
            raise ValueError(msg)
        earlier.append(value)

    def series(self) -> dict[str, Series]:
        """Each name's samples so far, in the order the names were first recorded."""
        return {name: _series(values) for name, values in self._values.items()}


def _series(values: Sequence[Sample]) -> Series:
    """`values`, of one kind as `SampleLog.add` keeps them, as that kind's Series."""
    if isinstance(values[0], str):
        return Categories(tuple(str(value) for value in values))
    return Numbers(tuple(float(value) for value in values))


@dataclass(frozen=True, slots=True)
class Spread:
    """A side's numbers of one name, in brief.

    Attributes:
        samples: How many.
        median: Their median.
        quartiles: Their lower and upper quartiles (`statistics.quantiles`, inclusive).
    """

    samples: int
    median: float
    quartiles: tuple[float, float]


@dataclass(frozen=True, slots=True)
class Shares:
    """A side's categories of one name, in brief.

    Attributes:
        samples: How many.
        shares: Each category's share of them, to three decimals, in category order.
    """

    samples: int
    shares: tuple[tuple[str, float], ...]


type Summary = Spread | Shares | None
"""A side's samples of one name, in brief; None if it has none."""


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
    reference: Mapping[str, Series], candidate: Mapping[str, Series]
) -> tuple[Decision, ...]:
    """Each sample name either side has, in name order: do the two sides' samples differ?

    Numbers are tested with `kolmogorov_smirnov`, categories with `chi_square`, and the
    p-values of the names tested are corrected together (`holm`), so a Group with several
    names still rejects one by chance at most `ALPHA` of the time. A name no test can tell
    apart (one category, or one number, on both sides) is left out of the correction, and
    does not reject.
    """
    names = sorted({*reference, *candidate})
    comparable = {
        name: _tested(ours, theirs)
        for name in names
        if (ours := reference.get(name)) is not None
        and (theirs := candidate.get(name)) is not None
        and type(ours) is type(theirs)
    }
    differences = {name: found for name, found in comparable.items() if found is not None}
    adjusted = dict(zip(differences, holm([d.p_value for d in differences.values()]), strict=True))
    return tuple(
        Decision(
            name=name,
            rejected=name not in comparable or adjusted.get(name, 1.0) <= ALPHA,
            difference=differences.get(name),
            p_value=adjusted.get(name),
            reference=summary(reference.get(name)),
            candidate=summary(candidate.get(name)),
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


def summary(series: Series | None) -> Summary:
    """`series` in brief (`Summary`): their median and quartiles, or each category's share."""
    match series:
        case None:
            return None
        case Categories(values):
            counts = Counter(values)
            shares = tuple((name, round(counts[name] / len(values), 3)) for name in sorted(counts))
            return Shares(samples=len(values), shares=shares)
        case Numbers(values):
            lower, median, upper = statistics.quantiles(values, n=4, method="inclusive")
            return Spread(samples=len(values), median=median, quartiles=(lower, upper))


def _tested(reference: Series, candidate: Series) -> Difference | None:
    """The two-sample test of one name's samples, of one kind on both sides, or None.

    None if no test applies: one number, or one category after pooling, on both sides.
    """
    if isinstance(reference, Categories) and isinstance(candidate, Categories):
        return chi_square(reference.values, candidate.values)
    if isinstance(reference, Numbers) and isinstance(candidate, Numbers):
        if len({*reference.values, *candidate.values}) == 1:
            return None
        return kolmogorov_smirnov(reference.values, candidate.values)
    return None


def kolmogorov_smirnov(reference: Sequence[float], candidate: Sequence[float]) -> Difference:
    """The two-sample Kolmogorov-Smirnov test of two samples of numbers.

    D is the largest gap between the two samples' cumulative shares. The p-value is exact
    given the pooled values, repeated ones included: the share of the ways to split them
    into the two samples that reach a gap that large (Hodges' count, the gap read only
    where the pooled values change, as Schröer and Trenkler's exact test with ties does).

    Raises:
        ValueError: A side has no samples.
    """
    _require_samples(reference, candidate)
    n, m = len(reference), len(candidate)
    gap = _largest_gap(sorted(reference), sorted(candidate))
    pooled_values = sorted((*reference, *candidate))
    changes = {k for k in range(1, n + m) if pooled_values[k - 1] != pooled_values[k]}
    return Difference(
        test="Kolmogorov-Smirnov",
        effect="D",
        effect_size=gap / (n * m),
        p_value=_reaching(gap, n, m, changes),
    )


def chi_square(reference: Sequence[str], candidate: Sequence[str]) -> Difference | None:
    """The chi-square test of homogeneity of two samples of categories.

    Categories under `MIN_EXPECTED` expected samples on a side are pooled first into one
    other category (`pooled`). If that leaves two categories, one of them still expected
    fewer than `MIN_EXPECTED` times, Fisher's exact test is used instead (`fisher_exact`).
    One category left means no test can tell the two samples apart: None.

    Raises:
        ValueError: A side has no samples.
    """
    _require_samples(reference, candidate)
    ours, theirs = Counter(reference), Counter(candidate)
    columns = pooled([(ours[name], theirs[name]) for name in sorted(ours | theirs)])
    if len(columns) < 2:  # noqa: PLR2004 - a test of homogeneity needs two categories
        return None
    statistic = _pearson(columns)
    total = len(reference) + len(candidate)
    effect_size = math.sqrt(statistic / total)
    if len(columns) == 2 and any(_sparse(columns)):  # noqa: PLR2004 - a 2 x 2 table
        first, second = columns
        p_value = fisher_exact(first, second)
        return Difference("Fisher's exact", "V", effect_size, p_value)
    return Difference(
        test="chi-square",
        effect="V",
        effect_size=effect_size,
        p_value=chi_square_survival(statistic, len(columns) - 1),
    )


def pooled(columns: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """`columns`, the two sides' counts per category, with the sparse ones pooled into one.

    A category is sparse when the side with fewer samples expects fewer than `MIN_EXPECTED`
    of it. The sparse ones are added together into one other category, last, so a category
    is never merged into a real one, which could hide it.
    """
    flags = _sparse(columns)
    sparse = [column for column, rare in zip(columns, flags, strict=True) if rare]
    common = [column for column, rare in zip(columns, flags, strict=True) if not rare]
    if not sparse:
        return common
    other = (sum(column[0] for column in sparse), sum(column[1] for column in sparse))
    return [*common, other]


def fisher_exact(first: tuple[int, int], second: tuple[int, int]) -> float:
    """Fisher's exact test of a 2 x 2 table: two categories' counts on each side.

    The chance, given the table's margins, of a table no likelier than this one: each
    table's weight is C(first's total, its count on the Reference) times the same for
    `second`, in integers, so ties in likelihood are found exactly.
    """
    reference = first[0] + second[0]
    firsts, seconds = sum(first), sum(second)

    def weight(count: int) -> int:
        return math.comb(firsts, count) * math.comb(seconds, reference - count)

    observed = weight(first[0])
    tables = range(max(0, reference - seconds), min(firsts, reference) + 1)
    weights = [weight(count) for count in tables]
    total = math.comb(firsts + seconds, reference)
    return float(Fraction(sum(w for w in weights if w <= observed), total))


def _sparse(columns: Sequence[tuple[int, int]]) -> list[bool]:
    """For each of `columns`, whether it is too sparse to test by chi-square.

    It is when the side with fewer samples expects it fewer than `MIN_EXPECTED` times.
    """
    fewer = min(sum(column[0] for column in columns), sum(column[1] for column in columns))
    total = sum(map(sum, columns))
    return [fewer * sum(column) < MIN_EXPECTED * total for column in columns]


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


def _reaching(gap: int, n: int, m: int, changes: AbstractSet[int]) -> float:
    """The share of the orderings of n and m values whose cumulative gap reaches `gap` / (n m).

    An ordering is a lattice path from (0, 0) to (n, m), a step for each pooled value in
    order. The gap can only be read after the last of equal values, so a path stays inside
    while every point (i, j) with i + j in `changes` (the counts of pooled values after
    which the next one is larger) has |i m - j n| < gap. A gap of 0 is reached by every
    ordering.
    """
    if gap == 0:
        return 1.0
    inside = [1] + [0] * m  # the paths to (i, j) that stayed inside, row i so far
    for i in range(n + 1):
        for j in range(m + 1):
            if i or j:
                inside[j] = (inside[j] if i else 0) + (inside[j - 1] if j else 0)
            if i + j in changes and abs(i * m - j * n) >= gap:
                inside[j] = 0
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
