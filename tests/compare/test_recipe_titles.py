"""The test cases of the recipe book and ghost recipe packets have titles (#62).

It covers a recipe of each kind of display in the book and as a ghost recipe (the crafting
table a joining player knows has tag ingredients and a stack result), requirements by tag, by
items and none, an empty book, and removals. Each is sent by one side only, and against each
other packet of its kind.
"""

import itertools
from collections.abc import Mapping

import pytest

from mscts.case_titles import TITLES
from mscts.compare import compare
from mscts.transcript import Transcript
from tests.codec.schemas.test_play_recipes import BOOK_ADD, CRAFTING_TABLE, RECIPE_DISPLAYS
from tests.compare.build import packet, transcript

LISTED = {
    "type": "minecraft:crafting_shaped",
    "value": {
        "width": 2,
        "height": 1,
        "ingredients": [
            {"type": "minecraft:empty", "value": None},
            {"type": "minecraft:tag", "value": {"ids": [63, 64]}},
        ],
        "result": {"type": "minecraft:item", "value": 63},
        "crafting_station": {"type": "minecraft:item", "value": 405},
    },
}
"""A shaped recipe with an empty cell and a cell of listed items."""
DISPLAYS = {
    "crafting_shaped": CRAFTING_TABLE,
    "listed": LISTED,
    **{key: display for key, (display, _) in RECIPE_DISPLAYS.items()},
}
"""A recipe display of each kind: the crafting table a joining player knows, and the others."""


def _book(display: object, requirements: object) -> dict[str, object]:
    """A recipe book of one recipe, shown by `display`, in a group."""
    contents = {
        "id": 300,
        "display": display,
        "group": 4,
        "category": 9,
        "crafting_requirements": requirements,
    }
    return {"entries": [{"contents": contents, "flags": 3}], "replace": False}


PACKETS: Mapping[str, tuple[str, Mapping[str, object]]] = {
    "tag requirements": (BOOK_ADD, _book(CRAFTING_TABLE, [{"tag": "minecraft:planks"}])),
    "item requirements": (BOOK_ADD, _book(CRAFTING_TABLE, [{"ids": [1, 2]}])),
    "no requirements": (BOOK_ADD, _book(CRAFTING_TABLE, None)),
    "empty book": (BOOK_ADD, {"entries": [], "replace": True}),
    **{f"book {key}": (BOOK_ADD, _book(value, None)) for key, value in DISPLAYS.items()},
    **{
        f"ghost {key}": ("minecraft:place_ghost_recipe", {"window_id": 1, "recipe_display": value})
        for key, value in DISPLAYS.items()
    },
    "removal": ("minecraft:recipe_book_remove", {"recipes": [339, 4]}),
    "empty removal": ("minecraft:recipe_book_remove", {"recipes": []}),
}
"""Each packet a recipe Group compares, as (name, fields)."""


def _sent(key: str) -> Transcript:
    name, fields = PACKETS[key]
    return transcript(("alice", packet(name, fields=fields)))


def _untitled(reference: Transcript, candidate: Transcript) -> list[str]:
    return sorted(set(compare(reference, candidate, []).test_cases) - TITLES.keys())


@pytest.mark.parametrize("key", PACKETS)
def test_every_test_case_of_a_packet_the_candidate_left_out_has_a_title(key: str) -> None:
    assert _untitled(_sent(key), transcript()) == []


@pytest.mark.parametrize(
    ("reference", "candidate"),
    [
        pair
        for pair in itertools.permutations(PACKETS, 2)
        if PACKETS[pair[0]][0] == PACKETS[pair[1]][0]
    ],
)
def test_every_test_case_of_a_packet_the_candidate_sent_another_way_has_a_title(
    reference: str, candidate: str
) -> None:
    assert _untitled(_sent(reference), _sent(candidate)) == []


def test_no_recipe_title_repeats_a_word_or_another_title() -> None:
    titles = {
        name: title
        for name, title in TITLES.items()
        if name.split(".")[0] in {"recipe_book_add", "recipe_book_remove", "place_ghost_recipe"}
    }

    assert [title for title in titles.values() if "recipe recipe" in title.lower()] == []
    assert len(set(titles.values())) == len(titles)
