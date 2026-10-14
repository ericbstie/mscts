"""How a statistical Group's samples are judged, name by name (#24)."""

import random
from collections.abc import Mapping

import pytest
from support.samples import RARE_ITEMS_P, rare_items

from mscts.stats import (
    ALPHA,
    PERMUTATION_SEED,
    Categories,
    Decision,
    Difference,
    Numbers,
    Series,
    Shares,
    Spread,
    decide,
    holm,
)

_ONCE = (1,) * 5  # one sample in each of five plays
_LOW = Numbers((1.0, 2.0, 3.0, 4.0, 5.0), _ONCE)
_HIGH = Numbers((6.0, 7.0, 8.0, 9.0, 10.0), _ONCE)
_DISJOINT_P = 2 / 252  # kolmogorov_smirnov(_LOW, _HIGH).p_value
_LOW_SPREAD = Spread(samples=5, median=3.0, quartiles=(2.0, 4.0))


def _decide(
    reference: Mapping[str, Series], candidate: Mapping[str, Series]
) -> tuple[Decision, ...]:
    return decide(reference, candidate, rng=random.Random(PERMUTATION_SEED))


def _categories(*groups: tuple[str, int]) -> Categories:
    """`count` samples of each category, in order, one in each play."""
    values = tuple(name for name, count in groups for _ in range(count))
    return Categories(values, (1,) * len(values))


def test_holm_scales_each_p_value_by_its_rank_and_keeps_them_in_order() -> None:
    # Sorted: 0.01 * 3, 0.03 * 2, 0.04 * 1, each at least the one before it.
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_holm_caps_at_one() -> None:
    assert holm([0.6, 0.9]) == [1.0, 1.0]


def test_the_level_is_one_percent() -> None:
    assert ALPHA == 0.01


def test_alike_numbers_match_with_both_summaries() -> None:
    (decision,) = _decide(
        {"spawn.distance": _LOW}, {"spawn.distance": Numbers(tuple(reversed(_LOW.values)), _ONCE)}
    )

    assert decision == Decision(
        name="spawn.distance",
        rejected=False,
        difference=Difference("Kolmogorov-Smirnov", "D", 0.0, 1.0),
        p_value=1.0,
        reference=_LOW_SPREAD,
        candidate=_LOW_SPREAD,
    )


def test_shifted_numbers_reject_with_the_effect_size() -> None:
    (decision,) = _decide({"x": _LOW}, {"x": _HIGH})

    assert decision.rejected
    assert decision.difference is not None
    assert decision.difference.effect_size == 1.0
    assert decision.p_value == pytest.approx(_DISJOINT_P)
    assert decision.candidate == Spread(samples=5, median=8.0, quartiles=(7.0, 9.0))


def test_categories_are_tested_by_chi_square_with_their_shares() -> None:
    (decision,) = _decide(
        {"mob": _categories(("zombie", 50))},
        {"mob": _categories(("zombie", 20), ("skeleton", 30))},
    )

    assert decision.rejected
    assert decision.difference is not None
    assert decision.difference.test == "chi-square"
    assert decision.reference == Shares(samples=50, shares=(("zombie", 1.0),))
    assert decision.candidate == Shares(samples=50, shares=(("skeleton", 0.6), ("zombie", 0.4)))


def test_shares_are_rounded_to_three_decimals() -> None:
    three = _categories(("a", 1), ("b", 2))
    (decision,) = _decide({"c": three}, {"c": three})

    assert decision.reference == Shares(samples=3, shares=(("a", 0.333), ("b", 0.667)))


def test_holm_corrects_over_a_groups_names() -> None:
    alone = _decide({"x": _LOW}, {"x": _HIGH})
    together = _decide({"x": _LOW, "y": _LOW}, {"x": _HIGH, "y": _LOW})

    assert [decision.rejected for decision in alone] == [True]
    assert [(decision.name, decision.rejected) for decision in together] == [
        ("x", False),
        ("y", False),
    ]
    assert together[0].p_value == pytest.approx(2 * _DISJOINT_P)


def test_a_name_no_test_can_tell_apart_is_left_out_of_holms_correction() -> None:
    # One category on both sides, or one number: no test can find a difference in them.
    zombies, ones = _categories(("zombie", 5)), Numbers((1.0,) * 5, _ONCE)
    decisions = _decide(
        {"x": _LOW, "mob": zombies, "y": ones}, {"x": _HIGH, "mob": zombies, "y": ones}
    )

    assert [(d.name, d.rejected, d.difference, d.p_value) for d in decisions[:2]] == [
        ("mob", False, None, None),
        ("x", True, Difference("Kolmogorov-Smirnov", "D", 1.0, _DISJOINT_P), _DISJOINT_P),
    ]
    assert (decisions[2].rejected, decisions[2].p_value) == (False, None)


def test_a_name_one_side_never_sampled_rejects_untested() -> None:
    decisions = _decide({"x": _LOW, "y": _LOW}, {"x": _LOW})

    assert decisions[1] == Decision(
        name="y",
        rejected=True,
        difference=None,
        p_value=None,
        reference=_LOW_SPREAD,
        candidate=None,
    )
    assert decisions[0].p_value == 1.0  # the untested name is no comparison for Holm


def test_a_name_only_the_candidate_sampled_rejects_untested() -> None:
    (decision,) = _decide({}, {"x": Categories(("a",), (1,))})

    assert (decision.rejected, decision.difference, decision.reference) == (True, None, None)


def test_numbers_against_categories_reject_untested() -> None:
    (decision,) = _decide({"x": _LOW}, {"x": _categories(("a", 5))})

    assert (decision.rejected, decision.difference, decision.p_value) == (True, None, None)
    assert decision.candidate == Shares(samples=5, shares=(("a", 1.0),))


def test_names_come_in_name_order() -> None:
    decisions = _decide({"b": _LOW, "a": _LOW}, {"a": _LOW, "b": _LOW})

    assert [decision.name for decision in decisions] == ["a", "b"]


_PER_PLAY = "Kolmogorov-Smirnov on samples per play"


def test_far_fewer_samples_per_play_reject_though_the_values_cannot_be_told_apart() -> None:
    # Review B's probe: 10 zombies in each of 50 plays, against 2 pigs in 2 of 50 plays.
    zombies = Categories(("zombie",) * 500, (10,) * 50)
    pigs = Categories(("pig",) * 2, (1, 1) + (0,) * 48)

    (decision,) = _decide({"mob": zombies}, {"mob": pigs})

    assert decision.rejected
    assert decision.difference is not None
    assert (decision.difference.test, decision.difference.effect_size) == (_PER_PLAY, 1.0)


def test_one_sample_against_fifty_rejects_by_its_count() -> None:
    # Review B's probe: one number in 50 plays could never reach ALPHA by its value alone.
    near_zero = Numbers(tuple(i / 100 for i in range(50)), (1,) * 50)
    far = Numbers((1000.0,), (1,) + (0,) * 49)

    (decision,) = _decide({"spawn.distance": near_zero}, {"spawn.distance": far})

    assert decision.rejected
    assert decision.difference is not None
    assert decision.difference.test == _PER_PLAY


def test_a_permutation_test_draws_from_the_generator_it_is_given() -> None:
    reference, candidate = rare_items()

    (decision,) = _decide({"loot": reference}, {"loot": candidate})

    assert decision.difference is not None
    assert decision.p_value == RARE_ITEMS_P


def test_the_counts_are_corrected_with_the_values() -> None:
    # Both tests of each name join Holm's correction: two names, each with values and counts.
    shifted = Numbers(_HIGH.values, (1, 1, 1, 2, 0))
    decisions = _decide({"x": _LOW, "y": _LOW}, {"x": shifted, "y": _LOW})

    assert decisions[0].p_value == pytest.approx(3 * _DISJOINT_P)
