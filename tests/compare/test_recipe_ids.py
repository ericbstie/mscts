"""The recipe book's entries are compared in an order no server's numbering decides (#363).

The client puts each entry of `recipe_book_add` in its book, a map keyed by display id, so the
order of entries that show no toast is no difference; they are sorted by what each shows, with
the server's display id and group number left out. The toast shows the others one after
another in the order they came, so those keep their order.
"""

from typing import NamedTuple

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


class Entry(NamedTuple):
    """A recipe book entry.

    Attributes:
        makes: The item its display makes.
        display_id: Its display id.
        group: Its group number, or None for no group.
        flags: Its flags.
        category: Its recipe book category.
    """

    makes: int
    display_id: int
    group: int | None = None
    flags: int = NO_TOAST
    category: int = 0

    def fields(self) -> dict[str, object]:
        """The entry as `recipe_book_add` holds it."""
        contents = {
            "id": self.display_id,
            "display": _display(self.makes),
            "group": self.group,
            "category": self.category,
            "crafting_requirements": None,
        }
        return {"contents": contents, "flags": self.flags}


def book_add(*entries: Entry) -> Packet:
    """A `recipe_book_add` of `entries`, added to the book."""
    fields = {"entries": [entry.fields() for entry in entries], "replace": False}
    return packet(BOOK_ADD, fields=fields)


def _diff(reference: Packet, candidate: Packet) -> list[tuple[str | None, object, object]]:
    verdict = compare(transcript(("alice", reference)), transcript(("alice", candidate)), [])
    return [(d.path, d.reference, d.candidate) for d in verdict.divergences]


PLANKS, STICKS = 20, 30
"""What two recipes make: the planks recipe's display sorts first."""


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
        Entry(PLANKS, display_id=7, flags=0), Entry(PLANKS, display_id=1, flags=TOAST)
    )

    assert _diff(reference, candidate) == [
        ("entries[0].contents.display.value.result.value", STICKS, PLANKS)
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


def test_display_ids_are_numbered_in_the_sorted_order() -> None:
    reference = [book_add(Entry(STICKS, display_id=4), Entry(PLANKS, display_id=7)), book_remove(7)]
    candidate = [book_add(Entry(PLANKS, display_id=9), Entry(STICKS, display_id=4)), book_remove(4)]

    assert _diff_all(reference, candidate) == [("recipes[0]", "#1", "#2")]


def test_an_id_first_seen_in_a_removal_takes_the_next_number() -> None:
    reference = [book_remove(5), book_add(Entry(PLANKS, display_id=5, flags=TOAST))]

    assert (
        _diff_all(reference, [book_remove(8), book_add(Entry(PLANKS, display_id=8, flags=TOAST))])
        == []
    )
    assert _diff_all(
        reference, [book_remove(8), book_add(Entry(PLANKS, display_id=9, flags=TOAST))]
    ) == [("entries[0].contents.id", "#1", "#2")]


def test_two_groups_on_one_server_and_one_on_the_other_differ() -> None:
    reference = [
        book_add(Entry(PLANKS, display_id=7, group=3), Entry(STICKS, display_id=4, group=8))
    ]
    candidate = [
        book_add(Entry(PLANKS, display_id=100, group=9), Entry(STICKS, display_id=55, group=9))
    ]

    assert _diff_all(reference, candidate) == [("entries[1].contents.group", "#2", "#1")]


def test_no_group_takes_no_number() -> None:
    reference = [book_add(Entry(PLANKS, display_id=1), Entry(STICKS, display_id=2, group=7))]
    candidate = [
        book_add(Entry(PLANKS, display_id=1, group=4), Entry(STICKS, display_id=2, group=7))
    ]

    assert _diff_all(reference, candidate) == [
        ("entries[0].contents.group", None, "#1"),
        ("entries[1].contents.group", "#1", "#2"),
    ]


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
