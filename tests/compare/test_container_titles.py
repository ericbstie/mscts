"""The test cases of a container packet have titles and reference entries (#283).

It covers a stack with an int-valued component (`minecraft:damage`), a stack without
components, no stack, a stack sent by one side only, and a window with no slots. A component
whose value has fields of its own (an enchanted stack's `...added[].value[].enchantment`) names
test cases below its value, and those are not titled yet.
"""

import itertools
from collections.abc import Mapping

import pytest

from mscts.case_titles import TITLES
from mscts.compare import compare
from mscts.transcript import Transcript
from tests.compare.build import packet, transcript

CHEST_TITLE = bytes([0x08, 0x00, 0x05]) + b"Chest"
FULL = {
    "count": 2,
    "item": 1,
    "components": {
        "added": [{"type": "minecraft:damage", "value": 3}],
        "removed": ["minecraft:max_damage"],
    },
}
PLAIN = {"count": 2, "item": 1, "components": {"added": [], "removed": []}}
STACKS: Mapping[str, object] = {"full": FULL, "plain": PLAIN, "empty": None}
"""The stacks a slot can hold: one with every part a Comparison names, one with no components
(an empty list is a test case of its own), and none."""

STACK = object()
"""Where a packet in `PACKETS` holds a stack."""

PACKETS: Mapping[str, Mapping[str, object]] = {
    "open_screen": {"window_id": 3, "window_type": 2, "window_title": CHEST_TITLE},
    "mount_screen_open": {"window_id": 2, "inventory_columns": 5, "entity_id": 300},
    "container_set_content": {
        "window_id": 0,
        "state_id": 300,
        "slot_data": [STACK],
        "carried_item": STACK,
    },
    "container_set_slot": {"window_id": 1, "state_id": 5, "slot": 36, "slot_data": STACK},
    "container_set_data": {"window_id": 2, "property": 3, "value": -1},
    "container_close": {"window_id": 7},
    "set_cursor_item": {"slot_data": STACK},
    "set_player_inventory": {"slot": 40, "slot_data": STACK},
}
"""Each clientbound container packet, with a `STACK` wherever it holds one."""


def _holding(value: object, stack: object) -> object:
    """`value` with `stack` where it has `STACK`, in a list too."""
    if value is STACK:
        return stack
    return [_holding(item, stack) for item in value] if isinstance(value, list) else value


def _filled(name: str, stack: object) -> dict[str, object]:
    """The fields of the packet `name`, with `stack` wherever it holds one."""
    return {key: _holding(value, stack) for key, value in PACKETS[name].items()}


def _sent(name: str, fields: Mapping[str, object]) -> Transcript:
    """A Transcript of a Bot that was sent the packet `name` with `fields`."""
    return transcript(("alice", packet(f"minecraft:{name}", fields=fields)))


def _untitled(name: str, reference: Mapping[str, object], candidate: Transcript) -> list[str]:
    """The test cases of `reference` against `candidate` that `TITLES` has no title for."""
    cases = compare(_sent(name, reference), candidate, []).test_cases
    return sorted(set(cases) - TITLES.keys())


@pytest.mark.parametrize("stack", STACKS)
@pytest.mark.parametrize("name", PACKETS)
def test_every_test_case_of_a_packet_the_candidate_left_out_has_a_title(
    name: str, stack: str
) -> None:
    fields = _filled(name, STACKS[stack])
    assert name in compare(_sent(name, fields), transcript(), []).test_cases
    assert _untitled(name, fields, transcript()) == []


@pytest.mark.parametrize(("reference", "candidate"), list(itertools.permutations(STACKS, 2)))
@pytest.mark.parametrize("name", PACKETS)
def test_every_test_case_of_a_stack_the_candidate_sent_another_way_has_a_title(
    name: str, reference: str, candidate: str
) -> None:
    sent = _sent(name, _filled(name, STACKS[candidate]))
    assert _untitled(name, _filled(name, STACKS[reference]), sent) == []


def test_a_window_with_no_slots_or_more_slots_has_titles_too() -> None:
    none, few = _filled("container_set_content", None), _filled("container_set_content", FULL)
    empty = {**none, "slot_data": []}
    assert _untitled("container_set_content", empty, transcript()) == []
    assert _untitled("container_set_content", empty, _sent("container_set_content", few)) == []
    assert _untitled("container_set_content", few, _sent("container_set_content", empty)) == []
