"""The recipe book's entries are compared in an order no server's numbering decides (#363).

The client puts each entry of `recipe_book_add` in its book, a map keyed by display id, so the
order of entries that show no toast is no difference; they are sorted by what each shows, with
the server's display id and group number left out. The toast shows the others one after
another in the order they came, so those keep their order.
"""

import json
from collections.abc import Sequence
from typing import NamedTuple

import pytest

from mscts.codec.packets import Packet
from mscts.compare import ABSENT, MASKED, UNORDERED, Mask, compare
from mscts.compare import OBSERVE_CLOSE as CLOSE
from mscts.compare import OBSERVE_OPEN as OPEN
from tests.compare.build import packet, transcript

BOOK_ADD = "minecraft:recipe_book_add"
NO_TOAST, TOAST = 2, 3
"""Entry flags: highlighted only, as at a join; and a toast too, as for a recipe given."""


def _display(result: int, station: int = 1) -> dict[str, object]:
    """A shapeless recipe display of one item that makes item `result` at item `station`."""
    return {
        "type": "minecraft:crafting_shapeless",
        "value": {
            "ingredients": [{"type": "minecraft:item", "value": 1}],
            "result": {"type": "minecraft:item", "value": result},
            "crafting_station": {"type": "minecraft:item", "value": station},
        },
    }


class Entry(NamedTuple):
    """A recipe book entry.

    Attributes:
        makes: The item its display makes.
        display_id: Its display id.
        group: Its group number, or None for no group.
        flags: Its flags.
        category: Its recipe book category.
        station: The item its display shows it is made at.
    """

    makes: int
    display_id: int
    group: int | None = None
    flags: int = NO_TOAST
    category: int = 0
    station: int = 1

    def fields(self) -> dict[str, object]:
        """The entry as `recipe_book_add` holds it."""
        contents = {
            "id": self.display_id,
            "display": _display(self.makes, self.station),
            "group": self.group,
            "category": self.category,
            "crafting_requirements": None,
        }
        return {"contents": contents, "flags": self.flags}


def book_add(*entries: Entry, replace: bool = False) -> Packet:
    """A `recipe_book_add` of `entries`, added to the book, or in its place if `replace`."""
    fields = {"entries": [entry.fields() for entry in entries], "replace": replace}
    return packet(BOOK_ADD, fields=fields)


def _diff(reference: Packet, candidate: Packet) -> list[tuple[str | None, object, object]]:
    verdict = compare(transcript(("alice", reference)), transcript(("alice", candidate)), [])
    return [(d.path, d.reference, d.candidate) for d in verdict.divergences]


PLANKS, STICKS, BREAD = 20, 30, 40
"""What three recipes make: the planks recipe's display sorts first."""


def test_the_order_of_entries_with_no_toast_is_no_difference() -> None:
    planks, sticks = Entry(PLANKS, display_id=7), Entry(STICKS, display_id=4)

    assert _diff(book_add(planks, sticks), book_add(sticks, planks)) == []


def test_entries_with_no_toast_are_sorted_by_what_they_show_not_by_their_display_id() -> None:
    reference = book_add(Entry(STICKS, display_id=4), Entry(PLANKS, display_id=7))
    candidate = book_add(Entry(PLANKS, display_id=3), Entry(STICKS, display_id=9))

    assert _diff(reference, candidate) == []


def test_entries_that_show_the_same_are_sorted_by_whether_they_have_a_group() -> None:
    reference = book_add(Entry(PLANKS, display_id=1), Entry(PLANKS, display_id=2, group=5))
    candidate = book_add(Entry(PLANKS, display_id=3, group=8), Entry(PLANKS, display_id=4))

    assert _diff(reference, candidate) == []


def test_entries_that_show_the_same_are_not_sorted_by_display_id() -> None:
    reference = book_add(Entry(PLANKS, display_id=1), Entry(PLANKS, display_id=2, group=5))
    candidate = book_add(Entry(PLANKS, display_id=9), Entry(PLANKS, display_id=3, group=5))

    assert _diff(reference, candidate) == []


def test_entries_that_show_the_same_keep_the_order_they_came_in_whatever_their_numbers() -> None:
    reference = book_add(
        Entry(PLANKS, display_id=1, group=5),
        Entry(PLANKS, display_id=2, group=6),
        Entry(STICKS, display_id=3, group=5),
    )
    other_ids = book_add(
        Entry(PLANKS, display_id=9, group=5),
        Entry(PLANKS, display_id=4, group=6),
        Entry(STICKS, display_id=5, group=5),
    )
    other_groups = book_add(
        Entry(PLANKS, display_id=7, group=9),
        Entry(PLANKS, display_id=8, group=2),
        Entry(STICKS, display_id=9, group=9),
    )

    assert _diff(reference, other_ids) == []
    assert _diff(reference, other_groups) == []


def test_entries_with_a_toast_keep_their_order_since_the_toast_shows_them_in_turn() -> None:
    planks, sticks = (
        Entry(PLANKS, display_id=7, flags=TOAST),
        Entry(STICKS, display_id=4, flags=TOAST),
    )

    assert _diff(book_add(planks, sticks), book_add(sticks, planks)) != []


def test_entries_with_a_toast_come_first_then_the_others_sorted() -> None:
    toast, planks, sticks = (
        Entry(STICKS, display_id=1, flags=TOAST),
        Entry(PLANKS, display_id=7, flags=0),
        Entry(STICKS, display_id=4, flags=0),
    )

    assert _diff(book_add(planks, toast, sticks), book_add(toast, sticks, planks)) == []


def test_the_entries_with_a_toast_are_the_first_paths() -> None:
    reference = book_add(
        Entry(PLANKS, display_id=7, flags=0), Entry(STICKS, display_id=1, flags=TOAST)
    )
    candidate = book_add(
        Entry(PLANKS, display_id=7, flags=0), Entry(BREAD, display_id=1, flags=TOAST)
    )

    assert _diff(reference, candidate) == [
        ("entries[0].contents.display.value.result.value", STICKS, BREAD)
    ]


def test_an_entry_whose_flags_are_not_a_number_keeps_its_order() -> None:
    planks = Entry(PLANKS, display_id=7, flags=0).fields()
    sticks = Entry(STICKS, display_id=4, flags=0).fields()
    planks["flags"] = sticks["flags"] = None

    def unflagged(*entries: dict[str, object]) -> Packet:
        return packet(BOOK_ADD, fields={"entries": list(entries), "replace": False})

    assert _diff(unflagged(planks, sticks), unflagged(sticks, planks)) != []


def test_recipe_book_entries_are_compared_sorted_with_their_reason() -> None:
    reason = UNORDERED[BOOK_ADD]

    assert "Sets.newIdentityHashSet" in reason
    assert "RecipeToast" in reason


BOOK_REMOVE = "minecraft:recipe_book_remove"


def book_remove(*display_ids: int) -> Packet:
    """A `recipe_book_remove` of `display_ids`."""
    return packet(BOOK_REMOVE, fields={"recipes": list(display_ids)})


def ghost(result: int) -> Packet:
    """A `place_ghost_recipe` in the inventory's grid of the recipe that makes `result`."""
    return packet(
        "minecraft:place_ghost_recipe", fields={"window_id": 0, "recipe_display": _display(result)}
    )


def _diff_all(
    reference: Sequence[Packet | str], candidate: Sequence[Packet | str]
) -> list[tuple[str | None, object, object]]:
    """The divergences of `reference` and `candidate`: alice's packets, and a string a Mark."""
    verdict = compare(
        transcript(*(_alices(each) for each in reference)),
        transcript(*(_alices(each) for each in candidate)),
        [],
    )
    return [(d.path, d.reference, d.candidate) for d in verdict.divergences]


def _alices(item: Packet | str) -> tuple[str, Packet] | str:
    """`item` as `transcript` takes it: a packet alice receives, or the label of a Mark."""
    return item if isinstance(item, str) else ("alice", item)


def test_a_server_that_numbers_every_recipe_another_way_but_consistently_matches() -> None:
    reference = [
        book_add(Entry(PLANKS, display_id=7, group=3), Entry(STICKS, display_id=4, group=3)),
        book_remove(4),
        book_add(Entry(STICKS, display_id=4, group=3, flags=TOAST)),
    ]
    candidate = [
        book_add(Entry(STICKS, display_id=55, group=9), Entry(PLANKS, display_id=100, group=9)),
        book_remove(55),
        book_add(Entry(STICKS, display_id=55, group=9, flags=TOAST)),
    ]

    assert _diff_all(reference, candidate) == []


def test_a_removal_of_another_recipe_than_the_reference_removes_differs() -> None:
    reference = [book_add(Entry(PLANKS, display_id=7), Entry(STICKS, display_id=4)), book_remove(4)]
    candidate = [
        book_add(Entry(PLANKS, display_id=100), Entry(STICKS, display_id=55)),
        book_remove(100),
    ]

    assert _diff_all(reference, candidate) == [("recipes[0]", "#2", "#1")]


def test_the_order_of_a_removal_is_no_difference() -> None:
    added = book_add(Entry(PLANKS, display_id=7), Entry(STICKS, display_id=4))

    assert _diff_all([added, book_remove(7, 4)], [added, book_remove(4, 7)]) == []
    assert _diff_all([added, book_remove(9, 7)], [added, book_remove(7, 9)]) == []


def test_a_removed_value_that_is_no_display_id_is_compared_after_the_ids() -> None:
    def removal(*recipes: object) -> Packet:
        return packet(BOOK_REMOVE, fields={"recipes": list(recipes)})

    assert _diff_all([removal(None, 7)], [removal(7, "x")]) == [("recipes[1]", None, "x")]


def test_a_removal_is_compared_sorted_with_its_reason() -> None:
    reason = UNORDERED[BOOK_REMOVE]

    assert "handleRecipeBookRemove" in reason
    assert "ClientRecipeBook.remove" in reason


def test_display_ids_are_numbered_in_the_sorted_order() -> None:
    reference = [book_add(Entry(STICKS, display_id=4), Entry(PLANKS, display_id=7)), book_remove(7)]
    candidate = [book_add(Entry(PLANKS, display_id=9), Entry(STICKS, display_id=4)), book_remove(4)]

    assert _diff_all(reference, candidate) == [("recipes[0]", "#1", "#2")]


def test_an_id_first_seen_in_a_removal_takes_a_number_the_removal_ends() -> None:
    reference = [book_remove(5), book_add(Entry(PLANKS, display_id=5, flags=TOAST))]
    candidate = [book_remove(8), book_add(Entry(PLANKS, display_id=9, flags=TOAST))]

    assert _diff_all(reference, candidate) == []


def test_an_id_the_book_does_not_hold_takes_another_number_at_each_removal() -> None:
    assert _diff_all([book_remove(5), book_remove(5)], [book_remove(8), book_remove(9)]) == []


def test_a_recipe_added_again_after_its_removal_may_take_another_display_id() -> None:
    planks_as = [Entry(PLANKS, display_id=each, flags=TOAST) for each in (5, 8, 9)]
    reference = [book_add(planks_as[0]), book_remove(5), book_add(planks_as[0])]
    candidate = [book_add(planks_as[1]), book_remove(8), book_add(planks_as[2])]

    assert _diff_all(reference, candidate) == []


def test_an_id_given_to_another_recipe_while_the_first_holds_it_differs() -> None:
    planks, sticks = Entry(PLANKS, display_id=5), Entry(STICKS, display_id=6)
    reference = [book_add(planks, sticks), book_remove(5), book_add(Entry(PLANKS, display_id=7))]
    candidate = [book_add(planks, sticks), book_remove(5), book_add(Entry(PLANKS, display_id=6))]

    assert _diff_all(reference, candidate) == [
        ("entries[0].contents.id", "#1", "#1 in place of #2")
    ]


def test_a_recipe_given_again_at_its_own_id_takes_nothing_s_place() -> None:
    planks_at = [Entry(PLANKS, display_id=each) for each in (5, 9)]
    reference = [book_add(planks_at[0]), book_add(planks_at[0])]
    candidate = [book_add(planks_at[1]), book_add(planks_at[0], replace=True)]

    assert _diff_all(reference, candidate) == [("replace", False, True)]


def test_a_book_replaced_is_emptied_first() -> None:
    planks_as = [Entry(PLANKS, display_id=each, group=each) for each in (5, 9)]
    sticks_as = [Entry(STICKS, display_id=each) for each in (6, 5)]
    reference = [book_add(planks_as[0], replace=True)] * 2 + [book_add(sticks_as[0])]
    candidate = [book_add(planks_as[0], replace=True), book_add(planks_as[1], replace=True)]

    assert _diff_all(reference, [*candidate, book_add(sticks_as[1])]) == []


def test_a_recipe_taken_outside_the_windows_and_given_another_id_shows_the_same() -> None:
    planks_as = [Entry(PLANKS, display_id=each, flags=TOAST) for each in (5, 8, 9)]
    reference = [OPEN, book_add(planks_as[0]), CLOSE, book_remove(5)]
    candidate = [OPEN, book_add(planks_as[1]), CLOSE, book_remove(8)]

    assert (
        _diff_all(
            [*reference, OPEN, book_add(planks_as[0]), CLOSE],
            [*candidate, OPEN, book_add(planks_as[2]), CLOSE],
        )
        == []
    )


def test_a_book_replaced_outside_the_windows_keeps_its_recipes_numbers() -> None:
    planks_as = [Entry(PLANKS, display_id=each, flags=TOAST) for each in (5, 8, 2)]
    reference = [
        OPEN,
        book_add(planks_as[0]),
        CLOSE,
        book_add(Entry(STICKS, display_id=6), replace=True),
        OPEN,
        book_add(planks_as[0]),
        CLOSE,
    ]
    candidate = [
        OPEN,
        book_add(planks_as[1]),
        CLOSE,
        book_add(Entry(STICKS, display_id=1), replace=True),
        OPEN,
        book_add(planks_as[2]),
        CLOSE,
    ]

    assert _diff_all(reference, candidate) == []


def test_a_book_replaced_is_emptied_before_its_entries_take_their_place() -> None:
    planks, sticks_as = (
        Entry(PLANKS, display_id=5),
        [Entry(STICKS, display_id=each) for each in (5, 6)],
    )
    reference = [book_add(planks), book_add(sticks_as[0], replace=True)]
    candidate = [book_add(planks), book_add(sticks_as[1], replace=True)]

    assert _diff_all(reference, candidate) == []


def named(entry: Entry) -> str:
    """The name of `entry`'s recipe got outside the windows: the entry as JSON, but id and flags."""
    contents = {
        "display": _display(entry.makes, entry.station),
        "group": entry.group is not None,
        "category": entry.category,
        "crafting_requirements": None,
    }
    return json.dumps({"contents": contents}, sort_keys=True)


PLANKS_NAME = (
    '{"contents": {"category": 0, "crafting_requirements": null, "display": {"type": '
    '"minecraft:crafting_shapeless", "value": {"crafting_station": {"type": "minecraft:item", '
    '"value": 1}, "ingredients": [{"type": "minecraft:item", "value": 1}], "result": {"type": '
    '"minecraft:item", "value": 20}}}, "group": true}}'
)
"""The name of the planks recipe in a group, got outside the windows."""


def test_a_recipe_got_outside_the_windows_is_named_by_what_it_shows() -> None:
    reference = [book_add(Entry(PLANKS, display_id=5, group=3)), OPEN, book_remove(5), CLOSE]
    candidate = [OPEN, book_remove(9), CLOSE]

    assert _diff_all(reference, candidate) == [("recipes[0]", PLANKS_NAME, "#1")]


def test_a_recipe_named_outside_the_windows_has_the_name_whatever_its_id_and_place() -> None:
    planks_as = [Entry(PLANKS, display_id=each, group=each) for each in (5, 8)]
    sticks_as = [Entry(STICKS, display_id=each) for each in (6, 5)]
    reference = [book_add(planks_as[0], sticks_as[0]), OPEN, book_remove(5), CLOSE]
    candidate = [book_add(sticks_as[1], planks_as[1]), OPEN, book_remove(8), CLOSE]

    assert _diff_all(reference, candidate) == []


STATION = Mask(BOOK_ADD, "entries[*].contents.display.value.crafting_station", reason="a test")
"""A Mask on the item a recipe display shows it is made at."""


def test_a_removal_of_recipes_got_outside_the_windows_is_sorted_by_their_names() -> None:
    added = book_add(Entry(PLANKS, display_id=7), Entry(STICKS, display_id=4))

    assert (
        _diff_all([added, OPEN, book_remove(7, 4), CLOSE], [added, OPEN, book_remove(4, 7), CLOSE])
        == []
    )


def test_a_recipe_named_outside_the_windows_takes_no_number_when_it_is_removed() -> None:
    planks, sticks = Entry(PLANKS, display_id=5), Entry(STICKS, display_id=6, flags=TOAST)
    reference = [book_add(planks), OPEN, book_remove(5), book_add(sticks), CLOSE]
    candidate = [book_add(planks), book_remove(5), OPEN, book_add(sticks), CLOSE]

    assert _diff_all(reference, candidate) == [(None, {"recipes": [named(planks)]}, ABSENT)]


def _diff_masked(
    reference: Sequence[Packet | str], candidate: Sequence[Packet | str], mask: Mask
) -> list[tuple[str | None, object, object]]:
    """The divergences of `reference` and `candidate`, as `_diff_all`'s, under `mask`."""
    verdict = compare(
        transcript(*(_alices(each) for each in reference)),
        transcript(*(_alices(each) for each in candidate)),
        [mask],
    )
    return [(d.path, d.reference, d.candidate) for d in verdict.divergences]


def test_a_recipe_got_outside_the_windows_is_named_by_what_it_shows_through_the_masks() -> None:
    removal = [OPEN, book_remove(5), CLOSE]
    reference = [book_add(Entry(PLANKS, display_id=5, group=3, station=1)), *removal]
    candidate = [book_add(Entry(PLANKS, display_id=5, group=3, station=2)), *removal]

    assert _diff_masked(reference, candidate, STATION) == []


def test_recipes_numbered_in_a_window_are_told_apart_only_by_what_the_masks_leave() -> None:
    planks = Entry(PLANKS, display_id=5)
    reference = [OPEN, book_add(planks, Entry(PLANKS, display_id=6)), CLOSE]
    candidate = [OPEN, book_add(planks, Entry(PLANKS, display_id=6, station=2)), CLOSE]

    assert _diff_masked(reference, candidate, STATION) == []


def test_a_recipe_got_outside_the_windows_under_a_mask_of_every_entry_is_named_masked() -> None:
    reference = [book_add(Entry(PLANKS, display_id=5)), OPEN, book_remove(5), CLOSE]
    candidate = [OPEN, book_remove(9), CLOSE]

    assert _diff_masked(reference, candidate, Mask(BOOK_ADD, "entries", reason="a test")) == [
        ("recipes[0]", json.dumps(MASKED), "#1")
    ]


def test_a_removal_of_another_recipe_after_an_uncompared_replace_differs() -> None:
    planks, sticks = Entry(PLANKS, display_id=5, flags=TOAST), Entry(STICKS, display_id=6)
    common = [OPEN, book_add(planks, sticks), CLOSE, book_add(planks, sticks, replace=True)]
    removal = [[OPEN, book_remove(each), CLOSE] for each in (5, 6)]

    assert _diff_all([*common, *removal[0]], [*common, *removal[1]]) == [("recipes[0]", "#1", "#2")]


def test_a_removal_of_another_recipe_taken_and_given_back_outside_the_windows_differs() -> None:
    planks, sticks = Entry(PLANKS, display_id=5, flags=TOAST), Entry(STICKS, display_id=6)
    common = [OPEN, book_add(planks, sticks), CLOSE, book_remove(5, 6), book_add(planks, sticks)]
    removal = [[OPEN, book_remove(each), CLOSE] for each in (5, 6)]

    assert _diff_all([*common, *removal[0]], [*common, *removal[1]]) == [("recipes[0]", "#1", "#2")]


def test_a_removal_of_another_recipe_taken_in_a_window_and_given_back_outside_differs() -> None:
    planks, sticks = Entry(PLANKS, display_id=5, flags=TOAST), Entry(STICKS, display_id=6)
    common = [OPEN, book_add(planks, sticks), CLOSE, OPEN, book_remove(5, 6), CLOSE]
    removal = [[OPEN, book_remove(each), CLOSE] for each in (5, 6)]
    given_back = [*common, book_add(planks, sticks)]

    assert _diff_all([*given_back, *removal[0]], [*given_back, *removal[1]]) == [
        ("recipes[0]", "#1", "#2")
    ]


def test_two_recipes_that_show_the_same_have_one_name() -> None:
    planks_as = [Entry(PLANKS, display_id=each) for each in (5, 6)]
    reference = [book_add(planks_as[0]), book_add(planks_as[1]), OPEN, book_remove(6), CLOSE]

    assert _diff_all(reference, [OPEN, book_remove(1), CLOSE]) == [
        ("recipes[0]", named(planks_as[0]), "#1")
    ]


def test_a_recipe_given_again_outside_the_windows_keeps_its_name() -> None:
    planks = Entry(PLANKS, display_id=5)
    removal = [OPEN, book_remove(5), CLOSE]

    assert (
        _diff_all([book_add(planks), book_add(planks), *removal], [book_add(planks), *removal])
        == []
    )


def test_a_book_replaced_outside_the_windows_names_its_recipes_again() -> None:
    reference = [
        book_add(Entry(PLANKS, display_id=5)),
        book_add(Entry(STICKS, display_id=5), replace=True),
        OPEN,
        book_remove(5),
        CLOSE,
    ]
    candidate = [book_add(Entry(STICKS, display_id=9)), OPEN, book_remove(9), CLOSE]

    assert _diff_all(reference, candidate) == []


def test_a_recipe_given_again_outside_the_windows_keeps_its_number() -> None:
    planks = Entry(PLANKS, display_id=5, flags=TOAST)
    given = [OPEN, book_add(planks), CLOSE]
    removal = [OPEN, book_remove(5), CLOSE]

    assert _diff_all([*given, book_add(planks), *removal], [*given, *removal]) == []


def test_a_recipe_one_server_alone_takes_and_gives_back_outside_the_windows_keeps_its_number() -> (
    None
):
    # Review A of #462, P2: the client ends with the same book on both sides.
    def given(display_id: int, *, again: bool) -> list[Packet | str]:
        planks = Entry(PLANKS, display_id=display_id, group=3, flags=TOAST)
        sticks = Entry(STICKS, display_id=display_id + 1, group=3, flags=TOAST)
        outside = [book_remove(display_id), book_add(planks)] if again else []
        return [OPEN, book_add(planks), CLOSE, *outside, OPEN, book_add(sticks), CLOSE]

    assert _diff_all(given(5, again=False), given(50, again=True)) == []


def test_a_book_one_server_alone_sends_again_outside_the_windows_keeps_its_numbers() -> None:
    # Review A of #462, P1: a Candidate that resyncs the book where vanilla sends nothing.
    planks, sticks = Entry(PLANKS, display_id=5, flags=TOAST), Entry(STICKS, display_id=6)
    given, removal = [OPEN, book_add(planks, sticks), CLOSE], [OPEN, book_remove(5), CLOSE]
    sent_again = book_add(planks, sticks, replace=True)

    assert _diff_all([*given, *removal], [*given, sent_again, *removal]) == []


def _given_with_a_new_id(*, group: int | None, taken_first: bool) -> list[Packet | str]:
    """Planks got outside the windows, then given again with a new id, the old one taken."""
    old, new = (Entry(PLANKS, display_id=each, group=group) for each in (5, 7))
    if taken_first:
        return [book_add(old), book_remove(5), book_add(new)]
    return [book_add(old), book_add(new), book_remove(5)]


def test_a_recipe_given_a_new_id_outside_the_windows_is_named_alike_in_either_order() -> None:
    # Review A of #462, P3 and P3b: both books end with one planks recipe.
    removal = [OPEN, book_remove(7), CLOSE]
    sticks = [OPEN, book_add(Entry(STICKS, display_id=6, group=3, flags=TOAST)), CLOSE]

    assert (
        _diff_all(
            [*_given_with_a_new_id(group=None, taken_first=True), *removal],
            [*_given_with_a_new_id(group=None, taken_first=False), *removal],
        )
        == []
    )
    assert (
        _diff_all(
            [*_given_with_a_new_id(group=3, taken_first=True), *sticks],
            [*_given_with_a_new_id(group=3, taken_first=False), *sticks],
        )
        == []
    )


def test_an_id_given_to_another_recipe_outside_the_windows_shows_the_recipe_it_holds() -> None:
    # Review B of #462, P1 and P1b: the Candidate's client removes sticks, not planks.
    planks, sticks = Entry(PLANKS, display_id=7, flags=TOAST), Entry(STICKS, display_id=9)
    removal = [OPEN, book_remove(7), CLOSE]
    sticks_at_7 = book_add(Entry(STICKS, display_id=7))

    assert _diff_all(
        [book_add(planks), book_add(sticks), *removal], [book_add(planks), sticks_at_7, *removal]
    ) == [("recipes[0]", named(planks), named(sticks))]
    given = [OPEN, book_add(planks), CLOSE]
    assert _diff_all([*given, book_add(sticks), *removal], [*given, sticks_at_7, *removal]) == [
        ("recipes[0]", "#1", named(sticks))
    ]


def test_an_id_given_to_another_recipe_outside_the_windows_changes_its_group() -> None:
    # Review B of #462, P1c: the Reference's button holds bread and sticks, the Candidate's
    # bread and planks.
    sticks, planks = Entry(STICKS, display_id=9, group=5), Entry(PLANKS, display_id=9, group=5)
    bread = [OPEN, book_add(Entry(BREAD, display_id=8, group=5, flags=TOAST)), CLOSE]

    assert _diff_all(
        [book_add(sticks), *bread],
        [book_add(Entry(STICKS, display_id=9)), book_add(planks), *bread],
    ) == [("entries[0].contents.group", f"#1, {named(sticks)}", f"#1, {named(planks)}")]


def test_recipes_that_show_the_same_are_written_alike_whatever_order_they_came_in() -> None:
    # Review B of #462, P2g and its converse: the same planks in groups 3 and 5, sent in
    # another order.
    reference = book_add(
        Entry(PLANKS, display_id=7, group=3),
        Entry(PLANKS, display_id=4, group=5),
        Entry(STICKS, display_id=6, group=3),
    )
    candidate = book_add(
        Entry(PLANKS, display_id=55, group=5),
        Entry(PLANKS, display_id=100, group=3),
        Entry(STICKS, display_id=60, group=3),
    )
    bread = [OPEN, book_add(Entry(BREAD, display_id=8, group=3, flags=TOAST)), CLOSE]

    assert _diff_all([reference, *bread], [candidate, *bread]) == []
    assert (
        _diff_all(
            [reference, OPEN, book_remove(4), CLOSE], [candidate, OPEN, book_remove(55), CLOSE]
        )
        == []
    )


def test_recipes_that_show_the_same_are_written_the_same_however_many_the_book_holds() -> None:
    planks_as = [Entry(PLANKS, display_id=each) for each in (5, 6, 7)]
    both = book_add(planks_as[0], planks_as[1])
    name = named(planks_as[0])

    assert _diff_all(
        [book_add(*planks_as), OPEN, book_remove(7, 6, 5), CLOSE],
        [OPEN, book_remove(1, 2, 3), CLOSE],
    ) == [
        ("recipes[0]", name, "#1"),
        ("recipes[1]", name, "#2"),
        ("recipes[2]", name, "#3"),
    ]
    assert (
        _diff_all(
            [both, book_remove(5), book_add(planks_as[2]), OPEN, book_remove(7), CLOSE],
            [book_add(planks_as[0]), OPEN, book_remove(5), CLOSE],
        )
        == []
    )


def test_a_recipe_in_another_group_after_an_uncompared_replace_differs() -> None:
    planks = Entry(PLANKS, display_id=5, group=3, flags=TOAST)
    common = [OPEN, book_add(planks), CLOSE, book_add(planks, replace=True)]

    def sticks_in(group: int) -> list[Packet | str]:
        return [OPEN, book_add(Entry(STICKS, display_id=6, group=group, flags=TOAST)), CLOSE]

    assert _diff_all([*common, *sticks_in(3)], [*common, *sticks_in(7)]) == [
        ("entries[0].contents.group", "#1, #2", "#2")
    ]


LOGIN = packet("minecraft:login", fields={})
"""A rejoin's `login`: `handleLogin` gives the new player a new, empty `ClientRecipeBook`."""


def test_a_rejoin_with_no_replace_shows_the_same_as_the_login_empties_the_book() -> None:
    planks = Entry(PLANKS, display_id=5, flags=TOAST)
    given = [OPEN, book_add(planks), CLOSE]

    assert _diff_all([*given, LOGIN, book_add(replace=True), *given], [*given, LOGIN, *given]) == []


def test_a_compared_login_empties_the_book() -> None:
    def rejoin(sticks_in: int) -> list[Packet | str]:
        planks, sticks = Entry(PLANKS, display_id=5, group=3), Entry(STICKS, 6, group=sticks_in)
        return [book_add(planks), LOGIN, book_add(sticks)]

    assert _diff_all(rejoin(3), rejoin(7)) == []


def test_a_login_outside_the_windows_empties_the_book() -> None:
    sticks = [OPEN, book_add(Entry(STICKS, display_id=6, group=3, flags=TOAST)), CLOSE]
    planks = [OPEN, book_add(Entry(PLANKS, display_id=5, group=3, flags=TOAST)), CLOSE]

    assert _diff_all([*sticks, LOGIN, *planks], [*sticks, LOGIN, book_remove(6), *planks]) == []


@pytest.mark.parametrize("name", [BOOK_REMOVE, BOOK_ADD])
def test_a_book_packet_that_did_not_decode_changes_no_book(name: str) -> None:
    sticks = [OPEN, book_add(Entry(STICKS, display_id=6, group=3, flags=TOAST)), CLOSE]
    planks = [OPEN, book_add(Entry(PLANKS, display_id=5, group=3, flags=TOAST)), CLOSE]

    assert _diff_all([*sticks, packet(name, b"\xff"), *planks], [*sticks, *planks]) == []


def _planks_again(group: int, *, before: Sequence[Packet | str] = ()) -> list[Packet | str]:
    """After `before`, planks in group 3 are added and taken, then added again in `group`."""
    planks = Entry(PLANKS, display_id=5, group=3, flags=TOAST)
    again = Entry(PLANKS, display_id=5, group=group, flags=TOAST)
    return [*before, OPEN, book_add(planks), book_remove(5), book_add(again), CLOSE]


def test_a_group_is_named_by_the_names_and_numbers_of_its_recipes() -> None:
    sticks = Entry(STICKS, display_id=6, group=3)
    reference = [book_add(sticks), OPEN, book_add(Entry(PLANKS, display_id=5, group=3)), CLOSE]
    candidate = [OPEN, book_add(Entry(PLANKS, display_id=9, group=3)), CLOSE]

    assert _diff_all(reference, candidate) == [
        ("entries[0].contents.group", f"#1, {named(sticks)}", "#1")
    ]


def test_a_recipe_alone_in_its_group_shows_the_same_whatever_the_group_number() -> None:
    assert _diff_all(_planks_again(3), _planks_again(4)) == []


def test_a_recipe_put_back_beside_another_recipe_or_apart_differs() -> None:
    sticks = [OPEN, book_add(Entry(STICKS, display_id=6, group=3)), CLOSE]

    assert _diff_all(_planks_again(3, before=sticks), _planks_again(4, before=sticks)) == [
        ("entries[0].contents.group", "#1, #2", "#2")
    ]


def test_a_recipe_got_outside_the_windows_names_its_group() -> None:
    sticks = Entry(STICKS, display_id=6, group=3)

    assert _diff_all(
        _planks_again(3, before=[book_add(sticks)]), _planks_again(4, before=[book_add(sticks)])
    ) == [("entries[0].contents.group", f"#1, {named(sticks)}", "#1")]


def test_a_book_replaced_takes_its_recipes_out_of_their_groups() -> None:
    sticks_as = [Entry(STICKS, display_id=6, group=3), Entry(STICKS, display_id=7)]
    replaced = [book_add(sticks_as[0]), book_add(sticks_as[1], replace=True)]

    assert _diff_all(_planks_again(3, before=replaced), _planks_again(4, before=replaced)) == []


def test_a_recipe_added_again_in_another_group_leaves_the_group_it_was_in() -> None:
    planks_in = [book_add(Entry(PLANKS, display_id=5, group=each)) for each in (3, 4)]
    reference = [*planks_in, book_add(Entry(STICKS, display_id=6, group=3))]
    candidate = [*planks_in, book_add(Entry(STICKS, display_id=6, group=9))]

    assert _diff_all(reference, candidate) == []


def test_the_order_of_two_book_packets_that_are_not_compared_is_no_difference() -> None:
    first = [OPEN, book_add(Entry(STICKS, display_id=6, group=3, flags=TOAST)), CLOSE]
    last = [OPEN, book_add(Entry(BREAD, display_id=7, group=3, flags=TOAST)), CLOSE]
    planks = book_add(Entry(PLANKS, display_id=5, group=3))
    in_window = f"{OPEN} minecraft:set_time"

    assert (
        _diff_all([*first, planks, book_remove(6), *last], [*first, book_remove(6), planks, *last])
        == []
    )
    assert (
        _diff_all(
            [*first, in_window, planks, book_remove(6), CLOSE, *last],
            [*first, in_window, book_remove(6), planks, CLOSE, *last],
        )
        == []
    )


def test_a_group_emptied_outside_the_windows_holds_only_what_comes_next() -> None:
    sticks = [OPEN, book_add(Entry(STICKS, display_id=6, group=3, flags=TOAST)), CLOSE]

    def planks_in(group: int) -> list[Packet | str]:
        return [OPEN, book_add(Entry(PLANKS, display_id=5, group=group, flags=TOAST)), CLOSE]

    assert (
        _diff_all(
            [*sticks, book_remove(6), *planks_in(3)], [*sticks, book_remove(6), *planks_in(8)]
        )
        == []
    )


def _planks_then_bread(planks_in: int, bread_in: int) -> list[Packet | str]:
    """Sticks given and taken in a window, then planks outside, then bread in a window."""
    sticks = book_add(Entry(STICKS, display_id=6, group=3, flags=TOAST))
    planks = book_add(Entry(PLANKS, display_id=5, group=planks_in))
    bread = book_add(Entry(BREAD, display_id=7, group=bread_in, flags=TOAST))
    return [OPEN, sticks, book_remove(6), CLOSE, planks, OPEN, bread, CLOSE]


def test_a_group_emptied_in_a_window_and_filled_outside_shows_what_fills_it() -> None:
    assert _diff_all(_planks_then_bread(3, 3), _planks_then_bread(12, 12)) == []


def test_a_group_emptied_in_a_window_and_filled_outside_differs_from_two_groups() -> None:
    planks = Entry(PLANKS, display_id=5, group=3)

    assert _diff_all(_planks_then_bread(3, 3), _planks_then_bread(3, 12)) == [
        ("entries[0].contents.group", f"#2, {named(planks)}", "#2")
    ]


def test_a_group_whose_recipes_leave_and_come_back_outside_the_windows_shows_the_same() -> None:
    sticks_as = [Entry(STICKS, display_id=6, group=each, flags=TOAST) for each in (3, 7)]
    in_window = f"{OPEN} minecraft:set_time"

    def regrouped(group: int, *, window: Sequence[str]) -> list[Packet | str]:
        sticks_again = book_add(Entry(STICKS, display_id=6, group=group))
        bread = book_add(Entry(BREAD, display_id=7, group=group, flags=TOAST))
        outside = [*window[:1], book_remove(6), sticks_again, *window[1:]]
        return [OPEN, book_add(sticks_as[0]), CLOSE, *outside, OPEN, bread, CLOSE]

    for window in ((), (in_window, CLOSE)):
        assert _diff_all(regrouped(3, window=window), regrouped(7, window=window)) == []


def test_two_groups_on_one_server_and_one_on_the_other_differ() -> None:
    reference = [
        book_add(Entry(PLANKS, display_id=7, group=3), Entry(STICKS, display_id=4, group=8))
    ]
    candidate = [
        book_add(Entry(PLANKS, display_id=100, group=9), Entry(STICKS, display_id=55, group=9))
    ]

    assert _diff_all(reference, candidate) == [
        ("entries[0].contents.group", "#1", "#1, #2"),
        ("entries[1].contents.group", "#2", "#1, #2"),
    ]


def test_one_group_number_in_two_categories_is_two_groups_as_in_the_client() -> None:
    shared = [
        Entry(PLANKS, display_id=7, group=3),
        Entry(STICKS, display_id=4, group=3, category=1),
    ]
    apart = [Entry(PLANKS, display_id=7, group=3), Entry(STICKS, display_id=4, group=8, category=1)]
    one_number = [Entry(PLANKS, display_id=7, group=9), Entry(STICKS, display_id=4, group=9)]

    assert _diff_all([book_add(*shared)], [book_add(*apart)]) == []
    assert _diff_all([book_add(*apart)], [book_add(*shared)]) == []
    assert _diff_all([book_add(*apart)], [book_add(*one_number)]) == [
        ("entries[0].contents.group", "#1", "#1, #2"),
        ("entries[1].contents.category", 1, 0),
        ("entries[1].contents.group", "#2", "#1, #2"),
    ]


def test_a_group_an_add_moves_its_only_recipe_out_of_holds_none() -> None:
    # The client puts the entries in turn (`known.put`), so the id ends in the last group.
    twice = book_add(Entry(PLANKS, display_id=5, group=3), Entry(PLANKS, display_id=5, group=4))
    once = book_add(Entry(PLANKS, display_id=5, group=3), Entry(PLANKS, display_id=5, group=3))

    assert _diff_all([twice], [once]) == [("entries[0].contents.group", "", "#1")]


def test_a_recipe_in_no_group_has_none() -> None:
    reference = [book_add(Entry(PLANKS, display_id=1), Entry(STICKS, display_id=2, group=7))]
    candidate = [
        book_add(Entry(PLANKS, display_id=1, group=4), Entry(STICKS, display_id=2, group=7))
    ]

    assert _diff_all(reference, candidate) == [("entries[0].contents.group", None, "#1")]


def test_a_recipe_in_a_group_on_one_server_only_differs() -> None:
    reference = [book_add(Entry(PLANKS, display_id=7, group=3))]
    candidate = [book_add(Entry(PLANKS, display_id=7))]

    assert _diff_all(reference, candidate) == [("entries[0].contents.group", "#1", None)]


def test_a_ghost_recipe_of_another_recipe_than_the_one_added_differs() -> None:
    reference = [book_add(Entry(PLANKS, display_id=7, flags=TOAST)), ghost(PLANKS)]
    candidate = [book_add(Entry(PLANKS, display_id=100, flags=TOAST)), ghost(STICKS)]

    assert _diff_all(reference, candidate) == [
        ("recipe_display.value.result.value", PLANKS, STICKS)
    ]


def test_each_bot_numbers_its_own_recipes() -> None:
    reference = transcript(
        ("alice", book_add(Entry(PLANKS, display_id=7, flags=TOAST))), ("bob", book_remove(7))
    )
    candidate = transcript(
        ("alice", book_add(Entry(PLANKS, display_id=9, flags=TOAST))), ("bob", book_remove(4))
    )

    assert compare(reference, candidate, []).divergences == ()
