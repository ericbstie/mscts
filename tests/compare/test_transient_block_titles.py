"""`add_transient_block` is compared by field, and its test cases have titles (#373).

Without a schema the packet was compared as its payload bytes, so a Divergence showed hex and
named only the packet.
"""

from collections.abc import Mapping

import pytest

from mscts.case_titles import TITLES
from mscts.compare import compare
from mscts.transcript import Transcript
from tests.compare.build import packet, transcript

LANDING: Mapping[str, object] = {"pos": {"x": 2, "y": -60, "z": 8}, "block_state": 121}
"""Sand landing at 2 -60 8, as vanilla sends it in `blocks/gravity`."""

NEAR_MISSES: Mapping[str, Mapping[str, object]] = {
    "block_state": {**LANDING, "block_state": 127},
    "pos.x": {**LANDING, "pos": {"x": 3, "y": -60, "z": 8}},
    "pos.y": {**LANDING, "pos": {"x": 2, "y": -59, "z": 8}},
    "pos.z": {**LANDING, "pos": {"x": 2, "y": -60, "z": 9}},
}
"""A landing that differs from `LANDING` in one field each."""


def _sent(fields: Mapping[str, object]) -> Transcript:
    """A Transcript of a Bot that was sent a landing with `fields`."""
    return transcript(("alice", packet("minecraft:add_transient_block", fields=fields)))


def test_a_landing_has_a_title_for_itself_and_each_of_its_fields() -> None:
    names = {name for name in TITLES if name.startswith("add_transient_block")}
    assert names == {
        "add_transient_block",
        "add_transient_block.block_state",
        "add_transient_block.pos.x",
        "add_transient_block.pos.y",
        "add_transient_block.pos.z",
    }


@pytest.mark.parametrize("field", NEAR_MISSES)
def test_a_landing_that_differs_in_one_field_names_that_field(field: str) -> None:
    verdict = compare(_sent(LANDING), _sent(NEAR_MISSES[field]), [])
    assert [(one.path, one.test_case) for one in verdict.divergences] == [
        (field, f"add_transient_block.{field}")
    ]


def test_a_landing_the_candidate_left_out_has_titles_for_every_case() -> None:
    cases = compare(_sent(LANDING), transcript(), []).test_cases
    assert "add_transient_block" in cases
    assert set(cases) - TITLES.keys() == set()
