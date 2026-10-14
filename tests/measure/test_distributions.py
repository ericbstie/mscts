"""The two-sample tests of statistical Groups, against published values (#24).

The chi-square critical values are the NIST/SEMATECH e-Handbook's table (section 1.3.6.7.4):
each is where the upper tail holds 1%, or 5% for 3.841. The other values were computed with
scipy 1.18.1 (`stats.ks_2samp(..., method="exact")`, `stats.chi2.sf`,
`stats.chi2_contingency(..., correction=False)`); the two disjoint samples of five are
Hodges' exact count: 2 of the C(10, 5) = 252 orderings put one sample wholly below the other.
"""

import math

import pytest

from mscts.stats import chi_square, chi_square_survival, kolmogorov_smirnov, pooled

_A = [0.61, 0.29, 0.06, 0.59, -1.73, -0.74, 0.51, -0.56, 0.39, 1.64, 0.05, -0.06, 0.64]
_A += [-0.82, 0.37, 1.77, 1.09, -1.28, 2.36, 1.31, 1.05, -0.32, -0.4, 1.06, -2.47]
_B = [2.2, 1.66, 1.38, 0.2, 0.36, 0.0, 0.96, 1.56, 0.44, 1.5, -0.3, 0.66, 2.31, 3.29]
_B += [-0.27, -0.37, 0.38, 0.7, 0.19, -2.18, 1.34, 0.86, 0.43, 2.22, 0.94, 1.63, 0.01, 1.41]


def test_ks_of_two_disjoint_samples_is_hodges_exact_count() -> None:
    found = kolmogorov_smirnov([1, 2, 3, 4, 5], [6, 7, 8, 9, 10])

    assert found.effect_size == 1.0
    assert found.p_value == pytest.approx(2 / 252, rel=1e-12)


def test_ks_matches_the_exact_two_sample_distribution() -> None:
    found = kolmogorov_smirnov(_A, _B)

    assert found.test == "Kolmogorov-Smirnov"
    assert found.effect == "D"
    assert found.effect_size == pytest.approx(0.2914285714285714, rel=1e-12)
    assert found.p_value == pytest.approx(0.16890741550233357, rel=1e-9)


def test_ks_is_the_same_either_way_round() -> None:
    assert kolmogorov_smirnov(_B, _A) == kolmogorov_smirnov(_A, _B)


def test_ks_of_the_same_values_finds_no_difference() -> None:
    found = kolmogorov_smirnov([3, 1, 2, 2], [2, 3, 1, 2])

    assert (found.effect_size, found.p_value) == (0.0, 1.0)


def test_ks_needs_samples_on_both_sides() -> None:
    with pytest.raises(ValueError, match="no samples"):
        kolmogorov_smirnov([1.0], [])


_CRITICAL = [
    (6.635, 1, 0.01),
    (9.210, 2, 0.01),
    (11.345, 3, 0.01),
    (13.277, 4, 0.01),
    (15.086, 5, 0.01),
    (3.841, 1, 0.05),
]

_SCIPY_TAILS = [
    (6.635, 1, 0.009999419574042536),
    (0.5, 7, 0.9994464813904249),
    (20.0, 9, 0.0179124045298433),
    (9.21, 2, 0.01000170200470548),
    (13.277, 4, 0.009998714430758818),
]


@pytest.mark.parametrize(("statistic", "df", "p"), _CRITICAL)
def test_chi_square_survival_meets_the_published_critical_values(
    statistic: float, df: int, p: float
) -> None:
    # The table rounds each value to 3 decimals, which moves the tail by up to 1.5e-5.
    assert chi_square_survival(statistic, df) == pytest.approx(p, abs=2e-5)


@pytest.mark.parametrize(("statistic", "df", "p"), _SCIPY_TAILS)
def test_chi_square_survival_matches_scipy(statistic: float, df: int, p: float) -> None:
    assert chi_square_survival(statistic, df) == pytest.approx(p, rel=1e-9)


def test_chi_square_survival_needs_a_degree_of_freedom() -> None:
    with pytest.raises(ValueError, match="at least 1 degree of freedom, not 0"):
        chi_square_survival(1.0, 0)


def test_chi_square_of_homogeneity_matches_a_contingency_table() -> None:
    reference = ["a"] * 20 + ["b"] * 15 + ["c"] * 15
    candidate = ["a"] * 10 + ["b"] * 25 + ["c"] * 15

    found = chi_square(reference, candidate)

    assert found.test == "chi-square"
    assert found.effect == "V"
    assert found.p_value == pytest.approx(0.05411376622282158, rel=1e-9)
    assert found.effect_size == pytest.approx(math.sqrt(5.833333333333334 / 100), rel=1e-12)


def test_categories_under_five_expected_are_pooled_until_none_is() -> None:
    # Rows of 48 and 52 samples: a category's smallest expected count is 48 * total / 100.
    columns = [(2, 1), (20, 25), (1, 0), (25, 26)]

    assert sorted(pooled(columns)) == [(23, 26), (25, 26)]


def test_a_category_with_five_expected_is_not_pooled() -> None:
    columns = [(5, 5), (5, 5), (40, 40)]

    assert sorted(pooled(columns)) == columns


def test_one_category_left_after_pooling_finds_no_difference() -> None:
    found = chi_square(["a"] * 3, ["a", "b"])

    assert (found.effect_size, found.p_value) == (0.0, 1.0)


def test_disjoint_categories_reject() -> None:
    found = chi_square(["a"] * 50, ["b"] * 50)

    assert found.effect_size == pytest.approx(1.0)
    assert found.p_value < 1e-20


def test_chi_square_needs_samples_on_both_sides() -> None:
    with pytest.raises(ValueError, match="no samples"):
        chi_square([], ["a"])
