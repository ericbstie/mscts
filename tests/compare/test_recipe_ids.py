"""The recipe book's entries are compared in an order no server's numbering decides (#363).

The client puts each entry of `recipe_book_add` in its book, a map keyed by display id, so the
order of entries that show no toast is no difference; they are sorted by what each shows, with
the server's display id and group number left out. The toast shows the others one after
another in the order they came, so those keep their order.
"""

from collections.abc import Sequence
from typing import NamedTuple

from mscts.codec.packets import Packet
from mscts.compare import OBSERVE_CLOSE as CLOSE
from mscts.compare import OBSERVE_OPEN as OPEN
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


def test_a_recipe_added_again_after_its_removal_may_take_another_display_id() -> None:
    planks_as = [Entry(PLANKS, display_id=each, flags=TOAST) for each in (5, 8, 9)]
    reference = [book_add(planks_as[0]), book_remove(5), book_add(planks_as[0])]
    candidate = [book_add(planks_as[1]), book_remove(8), book_add(planks_as[2])]

    assert _diff_all(reference, candidate) == []


def test_a_number_ended_is_never_given_again() -> None:
    planks, sticks = Entry(PLANKS, display_id=5), Entry(STICKS, display_id=6)
    reference = [book_add(planks, sticks), book_remove(5), book_add(Entry(PLANKS, display_id=7))]
    candidate = [book_add(planks, sticks), book_remove(5), book_add(Entry(PLANKS, display_id=6))]

    assert _diff_all(reference, candidate) == [("entries[0].contents.id", "#3", "#2")]


def test_a_book_replaced_ends_every_number() -> None:
    planks_as = [Entry(PLANKS, display_id=each, group=each) for each in (5, 9)]
    sticks_as = [Entry(STICKS, display_id=each) for each in (6, 5)]
    reference = [book_add(planks_as[0], replace=True)] * 2 + [book_add(sticks_as[0])]
    candidate = [book_add(planks_as[0], replace=True), book_add(planks_as[1], replace=True)]

    assert _diff_all(reference, [*candidate, book_add(sticks_as[1])]) == []


def test_a_removal_outside_the_windows_ends_its_numbers() -> None:
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


def test_a_book_replaced_outside_the_windows_ends_every_number() -> None:
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


def test_a_book_replaced_ends_every_number_before_its_entries_take_theirs() -> None:
    planks, sticks_as = (
        Entry(PLANKS, display_id=5),
        [Entry(STICKS, display_id=each) for each in (5, 6)],
    )
    reference = [book_add(planks), book_add(sticks_as[0], replace=True)]
    candidate = [book_add(planks), book_add(sticks_as[1], replace=True)]

    assert _diff_all(reference, candidate) == []


def test_a_removal_of_another_recipe_after_an_uncompared_replace_is_not_told_apart() -> None:
    # A known limit, until #462: the replace ends both ids' numbers, and the uncompared add
    # gives them none, so each removal takes the next number. #462 turns this red.
    planks, sticks = Entry(PLANKS, display_id=5, flags=TOAST), Entry(STICKS, display_id=6)
    common = [OPEN, book_add(planks, sticks), CLOSE, book_add(planks, sticks, replace=True)]
    removal = [[OPEN, book_remove(each), CLOSE] for each in (5, 6)]

    assert _diff_all([*common, *removal[0]], [*common, *removal[1]]) == []


def test_a_recipe_in_another_group_after_an_uncompared_replace_is_not_told_apart() -> None:
    # A known limit, until #462: the replace ends group 3's number while planks still hold
    # it, so sticks take the next number in either group. #462 turns this red.
    planks = Entry(PLANKS, display_id=5, group=3, flags=TOAST)
    common = [OPEN, book_add(planks), CLOSE, book_add(planks, replace=True)]

    def sticks_in(group: int) -> list[Packet | str]:
        return [OPEN, book_add(Entry(STICKS, display_id=6, group=group, flags=TOAST)), CLOSE]

    assert _diff_all([*common, *sticks_in(3)], [*common, *sticks_in(7)]) == []


def test_a_book_packet_that_did_not_decode_ends_no_number() -> None:
    planks_as = [Entry(PLANKS, display_id=each, flags=TOAST) for each in (5, 8, 9)]
    undecoded = packet(BOOK_REMOVE, b"\xff")
    reference = [
        OPEN,
        book_add(planks_as[0]),
        CLOSE,
        undecoded,
        OPEN,
        book_add(planks_as[0]),
        CLOSE,
    ]
    candidate = [
        OPEN,
        book_add(planks_as[1]),
        CLOSE,
        undecoded,
        OPEN,
        book_add(planks_as[2]),
        CLOSE,
    ]

    assert _diff_all(reference, candidate) == [("entries[0].contents.id", "#1", "#2")]


def _planks_again(group: int, *, before: Sequence[Packet | str] = ()) -> list[Packet | str]:
    """After `before`, planks in group 3 are added and taken, then added again in `group`."""
    planks = Entry(PLANKS, display_id=5, group=3, flags=TOAST)
    again = Entry(PLANKS, display_id=5, group=group, flags=TOAST)
    return [*before, OPEN, book_add(planks), book_remove(5), book_add(again), CLOSE]


def test_a_group_number_ends_with_the_last_recipe_in_the_group() -> None:
    assert _diff_all(_planks_again(3), _planks_again(4)) == []


def test_a_group_number_lasts_while_another_recipe_is_in_the_group() -> None:
    sticks = [OPEN, book_add(Entry(STICKS, display_id=6, group=3)), CLOSE]

    assert _diff_all(_planks_again(3, before=sticks), _planks_again(4, before=sticks)) == [
        ("entries[0].contents.group", "#1", "#2")
    ]


def test_a_recipe_got_outside_the_windows_keeps_its_group_number() -> None:
    sticks = [book_add(Entry(STICKS, display_id=6, group=3))]

    assert _diff_all(_planks_again(3, before=sticks), _planks_again(4, before=sticks)) == [
        ("entries[0].contents.group", "#1", "#2")
    ]


def test_a_book_replaced_takes_its_recipes_out_of_their_groups() -> None:
    sticks_as = [Entry(STICKS, display_id=6, group=3), Entry(STICKS, display_id=7)]
    replaced = [book_add(sticks_as[0]), book_add(sticks_as[1], replace=True)]

    assert _diff_all(_planks_again(3, before=replaced), _planks_again(4, before=replaced)) == []


def test_a_recipe_added_again_in_another_group_ends_the_number_of_the_group_it_left() -> None:
    planks_in = [book_add(Entry(PLANKS, display_id=5, group=each)) for each in (3, 4)]
    reference = [*planks_in, book_add(Entry(STICKS, display_id=6, group=3))]
    candidate = [*planks_in, book_add(Entry(STICKS, display_id=6, group=9))]

    assert _diff_all(reference, candidate) == []


def test_the_order_of_two_book_packets_that_are_not_compared_ends_no_group_number() -> None:
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


def test_a_group_emptied_outside_the_windows_is_numbered_again_at_the_next_add() -> None:
    sticks = [OPEN, book_add(Entry(STICKS, display_id=6, group=3, flags=TOAST)), CLOSE]

    def planks_in(group: int) -> list[Packet | str]:
        return [OPEN, book_add(Entry(PLANKS, display_id=5, group=group, flags=TOAST)), CLOSE]

    assert (
        _diff_all(
            [*sticks, book_remove(6), *planks_in(3)], [*sticks, book_remove(6), *planks_in(8)]
        )
        == []
    )


def test_a_group_emptied_in_a_window_is_numbered_again_if_it_is_filled_outside() -> None:
    def planks_then_bread(group: int) -> list[Packet | str]:
        sticks = book_add(Entry(STICKS, display_id=6, group=3, flags=TOAST))
        bread = book_add(Entry(BREAD, display_id=7, group=group, flags=TOAST))
        planks = book_add(Entry(PLANKS, display_id=5, group=group))
        return [OPEN, sticks, book_remove(6), CLOSE, planks, OPEN, bread, CLOSE]

    assert _diff_all(planks_then_bread(3), planks_then_bread(12)) == []


def test_two_groups_on_one_server_and_one_on_the_other_differ() -> None:
    reference = [
        book_add(Entry(PLANKS, display_id=7, group=3), Entry(STICKS, display_id=4, group=8))
    ]
    candidate = [
        book_add(Entry(PLANKS, display_id=100, group=9), Entry(STICKS, display_id=55, group=9))
    ]

    assert _diff_all(reference, candidate) == [("entries[1].contents.group", "#2", "#1")]


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
        ("entries[1].contents.category", 1, 0),
        ("entries[1].contents.group", "#2", "#1"),
    ]


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
