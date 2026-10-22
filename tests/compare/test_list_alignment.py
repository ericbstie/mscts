"""compare() lines up the lists `_LINED_UP` names before it compares their elements (#256).

An element one side has and the other lacks is one Divergence, at its index in the list
that has it; the elements around it are no difference. Elements that are not lined up,
as many on each side, are compared in place. Every other list is compared index by index.
"""

import itertools
from collections.abc import Sequence
from typing import cast
from uuid import UUID

import pytest

import mscts.compare
from mscts.compare import (
    ABSENT,
    _Edit,
    _fewest_edits,
    _pairs,
    _Path,
    _render,
    _same,
    _Value,
    compare,
)
from tests.compare.build import packet, transcript


def _lined_up(_path: _Path) -> bool:
    return True


def _diff(reference: object, candidate: object) -> list[tuple[str, object, object]]:
    """(path, reference, candidate) of each difference, with every list lined up."""
    pairs = _pairs(cast("_Value", reference), cast("_Value", candidate), (), _lined_up)
    return [(_render(path), ref, cand) for path, ref, cand in pairs if not _same(ref, cand)]


def _slots(first: int, items: Sequence[str]) -> list[object]:
    stacks = [{"item": item, "count": 1, "components": {}} for item in items]
    return [*([None] * first), *stacks, *([None] * (46 - first - len(stacks)))]


def test_a_list_that_is_not_named_is_compared_index_by_index() -> None:
    # A container's slot index is the slot: items one slot later are in the wrong slots,
    # each a difference, never lined up as the same items (review of #449).
    def content(slots: list[object]) -> dict[str, object]:
        return {"window_id": 0, "state_id": 1, "slot_data": slots, "carried_item": None}

    reference = _slots(36, ["stone", "dirt", "oak_log"])
    candidate = _slots(37, ["stone", "dirt", "oak_log"])
    verdict = compare(
        transcript(("alice", packet("minecraft:container_set_content", fields=content(reference)))),
        transcript(("alice", packet("minecraft:container_set_content", fields=content(candidate)))),
        [],
    )
    assert [(d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        ("slot_data[36]", reference[36], None),
        ("slot_data[37].item", "dirt", "stone"),
        ("slot_data[38].item", "oak_log", "dirt"),
        ("slot_data[39]", None, candidate[39]),
    ]


def test_an_element_left_out_at_the_front_is_one_missing_element() -> None:
    assert _diff({"l": ["a", "b", "c", "d"]}, {"l": ["b", "c", "d"]}) == [("l[0]", "a", ABSENT)]


def test_an_element_inserted_in_the_middle_is_one_extra_element_at_its_candidate_index() -> None:
    assert _diff({"l": [1, 2, 3, 4]}, {"l": [1, 2, 9, 3, 4]}) == [("l[2]", ABSENT, 9)]


def test_one_changed_element_in_a_long_list_is_one_change_in_place() -> None:
    reference = list(range(100))
    candidate = [*range(50), 999, *range(51, 100)]
    assert _diff({"l": reference}, {"l": candidate}) == [("l[50]", 50, 999)]


def test_a_repeated_element_left_out_is_one_missing_element() -> None:
    assert _diff({"l": ["a", "a", "b"]}, {"l": ["a", "b"]}) == [("l[1]", "a", ABSENT)]


def test_two_elements_compared_at_different_indexes_name_both() -> None:
    reference = {"l": ["x", "a", {"v": [1, 2, 3]}]}
    candidate = {"l": ["a", {"v": [1, 3]}]}
    assert _diff(reference, candidate) == [("l[0]", "x", ABSENT), ("l[2→1].v[1]", 2, ABSENT)]


def test_an_element_only_the_candidate_has_and_a_moved_pair_have_different_paths() -> None:
    # The reviews' case: named by the reference's index alone, the pair b, a was l[1] too.
    assert _diff({"l": ["a", "b"]}, {"l": ["b", "c", "a", "a"]}) == [
        ("l[0]", ABSENT, "b"),
        ("l[1]", ABSENT, "c"),
        ("l[1→3]", "b", "a"),
    ]


def test_no_two_differences_of_small_lists_share_a_path() -> None:
    for reference, candidate in itertools.product(_small_lists(), repeat=2):
        paths = [path for path, _, _ in _diff({"l": reference}, {"l": candidate})]
        assert len(paths) == len(set(paths)), (reference, candidate, paths)


def test_nested_lists_are_lined_up_too() -> None:
    reference = {"l": [[1, 2, 3], [4, 5, 6]]}
    candidate = {"l": [[2, 3], [4, 5, 6]]}
    assert _diff(reference, candidate) == [("l[0][0]", 1, ABSENT)]


def test_a_left_out_element_and_an_extra_one_at_another_place_are_one_each() -> None:
    assert _diff({"l": ["a", "b", "c", "d"]}, {"l": ["b", "c", "d", "e"]}) == [
        ("l[0]", "a", ABSENT),
        ("l[3]", ABSENT, "e"),
    ]


def test_a_change_and_a_left_out_element_side_by_side_compare_in_place_first() -> None:
    assert _diff({"l": ["a", "x", "y", "d"]}, {"l": ["a", "z", "d"]}) == [
        ("l[1]", "x", "z"),
        ("l[2]", "y", ABSENT),
    ]
    assert _diff({"l": ["a", "z", "d"]}, {"l": ["a", "x", "y", "d"]}) == [
        ("l[1]", "z", "x"),
        ("l[2]", ABSENT, "y"),
    ]


def test_changed_elements_ahead_of_an_extra_one_are_compared_in_place() -> None:
    reference = {"l": [{"id": "a", "data": None}, {"id": "b", "data": None}]}
    candidate = {"l": [{"id": "a", "data": 1}, {"id": "b", "data": 2}, {"id": "c", "data": 3}]}
    assert _diff(reference, candidate) == [
        ("l[0].data", None, 1),
        ("l[1].data", None, 2),
        ("l[2]", ABSENT, {"id": "c", "data": 3}),
    ]


def test_two_lists_with_nothing_in_common_and_one_length_are_compared_in_place() -> None:
    assert _diff({"l": [1, 2]}, {"l": [3, 4]}) == [("l[0]", 1, 3), ("l[1]", 2, 4)]


def test_swapped_elements_are_compared_in_place() -> None:
    assert _diff({"l": [1, 2]}, {"l": [2, 1]}) == [("l[0]", 1, 2), ("l[1]", 2, 1)]


def test_mappings_with_their_keys_in_another_order_line_up_as_equal() -> None:
    reference = {"l": [{"a": 1, "b": 2}, {"a": 3, "b": 4}]}
    candidate = {"l": [{"b": 4, "a": 3}]}
    assert _diff(reference, candidate) == [("l[0]", {"a": 1, "b": 2}, ABSENT)]


def test_bytes_and_uuids_line_up_by_value() -> None:
    assert _diff({"l": [b"a", b"b"]}, {"l": [b"b"]}) == [("l[0]", b"a", ABSENT)]
    first, second = UUID(int=1), UUID(int=2)
    assert _diff({"l": [first, second]}, {"l": [second]}) == [("l[0]", first, ABSENT)]


def _distance(reference: Sequence[str], candidate: Sequence[str]) -> int:
    """The fewest steps from one list to the other, by brute force over every edit."""
    if not reference or not candidate:
        return len(reference) + len(candidate)
    if reference[0] == candidate[0]:
        return _distance(reference[1:], candidate[1:])
    return 1 + min(
        _distance(reference[1:], candidate[1:]),
        _distance(reference[1:], candidate),
        _distance(reference, candidate[1:]),
    )


def _differing(reference: Sequence[str], candidate: Sequence[str], edits: list[_Edit]) -> int:
    return sum(i is None or j is None or reference[i] != candidate[j] for i, j in edits)


def _small_lists() -> list[list[str]]:
    """Every list up to length 4 over three values."""
    return [list(items) for length in range(5) for items in itertools.product("abc", repeat=length)]


def test_every_small_list_is_lined_up_in_order_in_fewest_steps_and_mirrored_by_a_swap() -> None:
    for reference, candidate in itertools.product(_small_lists(), repeat=2):
        edits = _fewest_edits(reference, candidate)
        assert [i for i, _ in edits if i is not None] == list(range(len(reference)))
        assert [j for _, j in edits if j is not None] == list(range(len(candidate)))
        assert _differing(reference, candidate, edits) == _distance(reference, candidate)
        assert _fewest_edits(candidate, reference) == [(j, i) for i, j in edits]


def test_of_the_fewest_steps_two_elements_are_compared_in_place_first() -> None:
    assert _fewest_edits(["x", "y"], ["z"]) == [(0, 0), (1, None)]
    assert _fewest_edits(["b", "c"], ["a", "b"]) == [(0, 0), (1, 1)]


def test_a_tie_leaves_the_smaller_element_on_its_own_whichever_side_it_is_on() -> None:
    # a, b, a against b, a, b: a left out at the front and b extra at the end, or b extra
    # at the front and a left out at the end. The smaller, a, is the one on its own first.
    assert _fewest_edits(["a", "b", "a"], ["b", "a", "b"]) == [(0, None), (1, 0), (2, 1), (None, 2)]
    assert _fewest_edits(["b", "a", "b"], ["a", "b", "a"]) == [(None, 0), (0, 1), (1, 2), (2, None)]


def test_lists_whose_middle_has_more_pairs_than_the_limit_are_compared_index_by_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Between the common ends, x, a, b against a, b, y is 3 by 3 pairs of elements.
    reference, candidate = ["x", "a", "b"], ["a", "b", "y"]
    monkeypatch.setattr(mscts.compare, "_LINE_UP_LIMIT", 9)
    assert _fewest_edits(reference, candidate) == [(0, None), (1, 0), (2, 1), (None, 2)]
    monkeypatch.setattr(mscts.compare, "_LINE_UP_LIMIT", 8)
    assert _fewest_edits(reference, candidate) == [(0, 0), (1, 1), (2, 2)]


@pytest.mark.timeout(10)
def test_two_long_lists_differing_at_both_ends_are_compared_in_time() -> None:
    # Lined up, 100,001 by 100,001 elements would take hours and 80 GB (review of #449).
    differences = _diff({"l": ["x", *range(100_000)]}, {"l": [*range(100_000), "y"]})
    assert differences[:2] == [("l[0]", "x", 0), ("l[1]", 0, 1)]
    assert len(differences) == 100_001


def test_values_python_calls_equal_are_not_lined_up_as_equal() -> None:
    assert _diff({"l": [1, True, 2]}, {"l": [True, 2]}) == [("l[0]", 1, ABSENT)]


def test_a_reordered_list_is_its_moved_elements_left_out_and_extra() -> None:
    assert _diff({"l": [1, 2, 3, 4]}, {"l": [4, 1, 2, 3]}) == [
        ("l[0]", ABSENT, 4),
        ("l[3]", 4, ABSENT),
    ]
