"""How a statistical Group's samples are judged, name by name (#24)."""

import pytest

from mscts.stats import ALPHA, Decision, Difference, decide, holm

_LOW = [1.0, 2.0, 3.0, 4.0, 5.0]
_HIGH = [6.0, 7.0, 8.0, 9.0, 10.0]
_DISJOINT_P = 2 / 252  # kolmogorov_smirnov(_LOW, _HIGH).p_value


def test_holm_scales_each_p_value_by_its_rank_and_keeps_them_in_order() -> None:
    # Sorted: 0.01 * 3, 0.03 * 2, 0.04 * 1, each at least the one before it.
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_holm_caps_at_one() -> None:
    assert holm([0.6, 0.9]) == [1.0, 1.0]


def test_the_level_is_one_percent() -> None:
    assert ALPHA == 0.01


def test_alike_numbers_match_with_both_summaries() -> None:
    (decision,) = decide({"spawn.distance": _LOW}, {"spawn.distance": list(reversed(_LOW))})

    assert decision == Decision(
        name="spawn.distance",
        rejected=False,
        difference=Difference("Kolmogorov-Smirnov", "D", 0.0, 1.0),
        p_value=1.0,
        reference={"samples": 5, "median": 3.0, "quartiles": [2.0, 4.0]},
        candidate={"samples": 5, "median": 3.0, "quartiles": [2.0, 4.0]},
    )


def test_shifted_numbers_reject_with_the_effect_size() -> None:
    (decision,) = decide({"x": _LOW}, {"x": _HIGH})

    assert decision.rejected
    assert decision.difference is not None
    assert decision.difference.effect_size == 1.0
    assert decision.p_value == pytest.approx(_DISJOINT_P)
    assert decision.candidate == {"samples": 5, "median": 8.0, "quartiles": [7.0, 9.0]}


def test_categories_are_tested_by_chi_square_with_their_shares() -> None:
    (decision,) = decide({"mob": ["zombie"] * 50}, {"mob": ["zombie"] * 20 + ["skeleton"] * 30})

    assert decision.rejected
    assert decision.difference is not None
    assert decision.difference.test == "chi-square"
    assert decision.reference == {"samples": 50, "shares": {"zombie": 1.0}}
    assert decision.candidate == {"samples": 50, "shares": {"skeleton": 0.6, "zombie": 0.4}}


def test_shares_are_rounded_to_three_decimals() -> None:
    (decision,) = decide({"c": ["a", "b", "b"]}, {"c": ["a", "b", "b"]})

    assert decision.reference == {"samples": 3, "shares": {"a": 0.333, "b": 0.667}}


def test_holm_corrects_over_a_groups_names() -> None:
    alone = decide({"x": _LOW}, {"x": _HIGH})
    together = decide({"x": _LOW, "y": _LOW}, {"x": _HIGH, "y": _LOW})

    assert [decision.rejected for decision in alone] == [True]
    assert [(decision.name, decision.rejected) for decision in together] == [
        ("x", False),
        ("y", False),
    ]
    assert together[0].p_value == pytest.approx(2 * _DISJOINT_P)


def test_a_name_one_side_never_sampled_rejects_untested() -> None:
    decisions = decide({"x": _LOW, "y": _LOW}, {"x": _LOW})

    assert decisions[1] == Decision(
        name="y",
        rejected=True,
        difference=None,
        p_value=None,
        reference={"samples": 5, "median": 3.0, "quartiles": [2.0, 4.0]},
        candidate={"samples": 0},
    )
    assert decisions[0].p_value == 1.0  # the untested name is no comparison for Holm


def test_a_name_only_the_candidate_sampled_rejects_untested() -> None:
    (decision,) = decide({}, {"x": ["a"]})

    assert (decision.rejected, decision.difference, decision.reference) == (
        True,
        None,
        {"samples": 0},
    )


def test_numbers_against_categories_reject_untested() -> None:
    (decision,) = decide({"x": _LOW}, {"x": ["a"] * 5})

    assert (decision.rejected, decision.difference, decision.p_value) == (True, None, None)
    assert decision.candidate == {"samples": 5, "shares": {"a": 1.0}}


def test_names_come_in_name_order() -> None:
    decisions = decide({"b": _LOW, "a": _LOW}, {"a": _LOW, "b": _LOW})

    assert [decision.name for decision in decisions] == ["a", "b"]
