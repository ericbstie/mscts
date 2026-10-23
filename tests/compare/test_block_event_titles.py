"""`block_event` is compared by field, and its test cases have titles (#442)."""

from collections.abc import Mapping

import pytest

from mscts.case_titles import TITLES
from mscts.compare import compare
from mscts.transcript import Transcript
from tests.compare.build import packet, transcript

ACTION: Mapping[str, object] = {
    "pos": {"x": 4, "y": -60, "z": 1},
    "action_id": 0,
    "action_parameter": 2,
    "block": 120,
}
"""A piston at 4 -60 1 told to extend."""

NEAR_MISSES: Mapping[str, Mapping[str, object]] = {
    "pos.x": {**ACTION, "pos": {"x": 5, "y": -60, "z": 1}},
    "pos.y": {**ACTION, "pos": {"x": 4, "y": -59, "z": 1}},
    "pos.z": {**ACTION, "pos": {"x": 4, "y": -60, "z": 2}},
    "action_id": {**ACTION, "action_id": 1},
    "action_parameter": {**ACTION, "action_parameter": 3},
    "block": {**ACTION, "block": 121},
}
"""An action that differs from `ACTION` in one field each."""


def _sent(fields: Mapping[str, object]) -> Transcript:
    """A Transcript of a Bot that was sent a block action with `fields`."""
    return transcript(("alice", packet("minecraft:block_event", fields=fields)))


def test_a_block_action_has_a_title_for_itself_and_each_of_its_fields() -> None:
    names = {name for name in TITLES if name.startswith("block_event")}
    assert names == {
        "block_event",
        "block_event.pos.x",
        "block_event.pos.y",
        "block_event.pos.z",
        "block_event.action_id",
        "block_event.action_parameter",
        "block_event.block",
    }


@pytest.mark.parametrize("field", NEAR_MISSES)
def test_a_block_action_that_differs_in_one_field_names_that_field(field: str) -> None:
    verdict = compare(_sent(ACTION), _sent(NEAR_MISSES[field]), [])
    assert [(one.path, one.test_case) for one in verdict.divergences] == [
        (field, f"block_event.{field}")
    ]


def test_a_block_action_the_candidate_left_out_has_titles_for_every_case() -> None:
    cases = compare(_sent(ACTION), transcript(), []).test_cases
    assert "block_event" in cases
    assert set(cases) - TITLES.keys() == set()
