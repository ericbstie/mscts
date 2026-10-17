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
    candidate = book_add((PLANKS, 8, None, NO_TOAST), (STICKS, 4, None, NO_TOAST))

    assert _diff(reference, candidate) == [("entries[0].contents.id", 7, 8)]


def test_entries_with_a_toast_keep_their_order_since_the_toast_shows_them_in_turn() -> None:
    planks, sticks = (PLANKS, 7, None, TOAST), (STICKS, 4, None, TOAST)

    assert _diff(book_add(planks, sticks), book_add(sticks, planks)) != []


def test_entries_with_a_toast_come_first_then_the_others_sorted() -> None:
    toast, planks, sticks = (STICKS, 1, None, TOAST), (PLANKS, 7, None, 0), (STICKS, 4, None, 0)

    assert _diff(book_add(planks, toast, sticks), book_add(toast, sticks, planks)) == []


def test_recipe_book_entries_are_compared_sorted_with_their_reason() -> None:
    reason = UNORDERED[BOOK_ADD]

    assert "Sets.newIdentityHashSet" in reason
    assert "RecipeToast" in reason
