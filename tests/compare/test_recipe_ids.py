"""The recipe book's entries are compared in an order no server's numbering decides (#363).

The client puts each entry of `recipe_book_add` in its book, a map keyed by display id, so the
order of entries that show no toast is no difference; they are sorted by what each shows, with
the server's display id and group number left out. The toast shows the others one after
another in the order they came, so those keep their order.
"""

from mscts.codec.packets import Packet
from mscts.compare import UNORDERED, compare
from tests.compare.build import packet, transcript

BOOK_ADD = "minecraft:recipe_book_add"
NO_TOAST, TOAST = 2, 3
"""Entry flags: highlighted only, as at a join; and a toast too, as for a recipe given."""


def _display(result: int) -> dict[str, object]:
    """A shapeless recipe display of one item that makes item `result`."""
    return {
        "type": "minecraft:crafting_shapeless",
        "value": {
            "ingredients": [{"type": "minecraft:item", "value": 1}],
            "result": {"type": "minecraft:item", "value": result},
            "crafting_station": {"type": "minecraft:item", "value": 1},
        },
    }


type _Entry = tuple[int, int, int | None, int]
"""An entry: what its display makes, its display id, its group number and its flags."""


def _entry(entry: _Entry) -> dict[str, object]:
    result, display_id, group, flags = entry
    contents = {
        "id": display_id,
        "display": _display(result),
        "group": group,
        "category": 0,
        "crafting_requirements": None,
    }
    return {"contents": contents, "flags": flags}


def book_add(*entries: _Entry) -> Packet:
    """A `recipe_book_add` of `entries`, added to the book."""
    fields = {"entries": [_entry(entry) for entry in entries], "replace": False}
    return packet(BOOK_ADD, fields=fields)


def _diff(reference: Packet, candidate: Packet) -> list[tuple[str | None, object, object]]:
    verdict = compare(transcript(("alice", reference)), transcript(("alice", candidate)), [])
    return [(d.path, d.reference, d.candidate) for d in verdict.divergences]


PLANKS, STICKS = 20, 30
"""What two recipes make: the planks recipe's display sorts first."""


def test_the_order_of_entries_with_no_toast_is_no_difference() -> None:
    planks, sticks = (PLANKS, 7, None, NO_TOAST), (STICKS, 4, None, NO_TOAST)

    assert _diff(book_add(planks, sticks), book_add(sticks, planks)) == []


def test_entries_with_no_toast_are_sorted_by_what_they_show_not_by_their_display_id() -> None:
    reference = book_add((STICKS, 4, None, NO_TOAST), (PLANKS, 7, None, NO_TOAST))
    candidate = book_add((PLANKS, 3, None, NO_TOAST), (STICKS, 9, None, NO_TOAST))

    assert _diff(reference, candidate) == []


def test_entries_that_show_the_same_are_sorted_by_whether_they_have_a_group() -> None:
    reference = book_add((PLANKS, 1, None, NO_TOAST), (PLANKS, 2, 5, NO_TOAST))
    candidate = book_add((PLANKS, 3, 8, NO_TOAST), (PLANKS, 4, None, NO_TOAST))

    assert _diff(reference, candidate) == []


def test_entries_that_show_the_same_are_not_sorted_by_display_id() -> None:
    reference = book_add((PLANKS, 1, None, NO_TOAST), (PLANKS, 2, 5, NO_TOAST))
    candidate = book_add((PLANKS, 9, None, NO_TOAST), (PLANKS, 3, 5, NO_TOAST))

    assert _diff(reference, candidate) == []


def test_entries_that_show_the_same_keep_the_order_they_came_in_whatever_their_numbers() -> None:
    reference = book_add(
        (PLANKS, 1, 5, NO_TOAST), (PLANKS, 2, 6, NO_TOAST), (STICKS, 3, 5, NO_TOAST)
    )
    other_ids = book_add(
        (PLANKS, 9, 5, NO_TOAST), (PLANKS, 4, 6, NO_TOAST), (STICKS, 5, 5, NO_TOAST)
    )
    other_groups = book_add(
        (PLANKS, 7, 9, NO_TOAST), (PLANKS, 8, 2, NO_TOAST), (STICKS, 9, 9, NO_TOAST)
    )

    assert _diff(reference, other_ids) == []
    assert _diff(reference, other_groups) == []


def test_entries_with_a_toast_keep_their_order_since_the_toast_shows_them_in_turn() -> None:
    planks, sticks = (PLANKS, 7, None, TOAST), (STICKS, 4, None, TOAST)

    assert _diff(book_add(planks, sticks), book_add(sticks, planks)) != []


def test_entries_with_a_toast_come_first_then_the_others_sorted() -> None:
    toast, planks, sticks = (STICKS, 1, None, TOAST), (PLANKS, 7, None, 0), (STICKS, 4, None, 0)

    assert _diff(book_add(planks, toast, sticks), book_add(toast, sticks, planks)) == []


def test_the_entries_with_a_toast_are_the_first_paths() -> None:
    reference = book_add((PLANKS, 7, None, 0), (STICKS, 1, None, TOAST))
    candidate = book_add((PLANKS, 7, None, 0), (PLANKS, 1, None, TOAST))

    assert _diff(reference, candidate) == [
        ("entries[0].contents.display.value.result.value", STICKS, PLANKS)
    ]


def test_an_entry_whose_flags_are_not_a_number_keeps_its_order() -> None:
    planks, sticks = _entry((PLANKS, 7, None, 0)), _entry((STICKS, 4, None, 0))
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
    reference: list[Packet], candidate: list[Packet]
) -> list[tuple[str | None, object, object]]:
    verdict = compare(
        transcript(*(("alice", each) for each in reference)),
        transcript(*(("alice", each) for each in candidate)),
        [],
    )
    return [(d.path, d.reference, d.candidate) for d in verdict.divergences]


def test_a_server_that_numbers_every_recipe_another_way_but_consistently_matches() -> None:
    reference = [
        book_add((PLANKS, 7, 3, NO_TOAST), (STICKS, 4, 3, NO_TOAST)),
        book_remove(4),
        book_add((STICKS, 4, 3, TOAST)),
    ]
    candidate = [
        book_add((STICKS, 55, 9, NO_TOAST), (PLANKS, 100, 9, NO_TOAST)),
        book_remove(55),
        book_add((STICKS, 55, 9, TOAST)),
    ]

    assert _diff_all(reference, candidate) == []


def test_a_removal_of_another_recipe_than_the_reference_removes_differs() -> None:
    reference = [book_add((PLANKS, 7, None, NO_TOAST), (STICKS, 4, None, NO_TOAST)), book_remove(4)]
    candidate = [
        book_add((PLANKS, 100, None, NO_TOAST), (STICKS, 55, None, NO_TOAST)),
        book_remove(100),
    ]

    assert _diff_all(reference, candidate) == [("recipes[0]", "#2", "#1")]


def test_display_ids_are_numbered_in_the_sorted_order() -> None:
    reference = [book_add((STICKS, 4, None, NO_TOAST), (PLANKS, 7, None, NO_TOAST)), book_remove(7)]
    candidate = [book_add((PLANKS, 9, None, NO_TOAST), (STICKS, 4, None, NO_TOAST)), book_remove(4)]

    assert _diff_all(reference, candidate) == [("recipes[0]", "#1", "#2")]


def test_an_id_first_seen_in_a_removal_takes_the_next_number() -> None:
    reference = [book_remove(5), book_add((PLANKS, 5, None, TOAST))]

    assert _diff_all(reference, [book_remove(8), book_add((PLANKS, 8, None, TOAST))]) == []
    assert _diff_all(reference, [book_remove(8), book_add((PLANKS, 9, None, TOAST))]) == [
        ("entries[0].contents.id", "#1", "#2")
    ]


def test_two_groups_on_one_server_and_one_on_the_other_differ() -> None:
    reference = [book_add((PLANKS, 7, 3, NO_TOAST), (STICKS, 4, 8, NO_TOAST))]
    candidate = [book_add((PLANKS, 100, 9, NO_TOAST), (STICKS, 55, 9, NO_TOAST))]

    assert _diff_all(reference, candidate) == [("entries[1].contents.group", "#2", "#1")]


def test_no_group_takes_no_number() -> None:
    reference = [book_add((PLANKS, 1, None, NO_TOAST), (STICKS, 2, 7, NO_TOAST))]
    candidate = [book_add((PLANKS, 1, 4, NO_TOAST), (STICKS, 2, 7, NO_TOAST))]

    assert _diff_all(reference, candidate) == [
        ("entries[0].contents.group", None, "#1"),
        ("entries[1].contents.group", "#1", "#2"),
    ]


def test_a_recipe_in_a_group_on_one_server_only_differs() -> None:
    reference = [book_add((PLANKS, 7, 3, NO_TOAST))]
    candidate = [book_add((PLANKS, 7, None, NO_TOAST))]

    assert _diff_all(reference, candidate) == [("entries[0].contents.group", "#1", None)]


def test_a_ghost_recipe_of_another_recipe_than_the_one_added_differs() -> None:
    reference = [book_add((PLANKS, 7, None, TOAST)), ghost(PLANKS)]
    candidate = [book_add((PLANKS, 100, None, TOAST)), ghost(STICKS)]

    assert _diff_all(reference, candidate) == [
        ("recipe_display.value.result.value", PLANKS, STICKS)
    ]


def test_each_bot_numbers_its_own_recipes() -> None:
    reference = transcript(("alice", book_add((PLANKS, 7, None, TOAST))), ("bob", book_remove(7)))
    candidate = transcript(("alice", book_add((PLANKS, 9, None, TOAST))), ("bob", book_remove(4)))

    assert compare(reference, candidate, []).divergences == ()
