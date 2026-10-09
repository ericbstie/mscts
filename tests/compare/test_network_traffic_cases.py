"""A test case only network traffic Divergences name is not one the Comparison compared (#330).

A field the canonical form leaves out (`_CANONICAL`), a status response member the client
never reads, and a chunk batch marker only one side sent show only as network traffic. If
`Verdict.test_cases` listed them when they differ, a Candidate that sends something else
would have more test cases than one that sends vanilla's bytes.
"""

from collections.abc import Mapping

import pytest

from mscts.codec.packets import Packet
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, TICK_MARK, TICK_PATH, Verdict, compare
from tests.compare.build import packet, transcript
from tests.compare.test_canonical import PUMPKIN_NIGHTLY, VANILLA, status

STONE = {"count": 64, "item": 1, "components": {"added": [], "removed": []}}
SLOT = {"window_id": 1, "state_id": 5, "slot": 36, "slot_data": STONE}
CONTENT = {"window_id": 0, "state_id": 5, "slot_data": [None, STONE], "carried_item": None}


def _fields(name: str, fields: Mapping[str, object]) -> Packet:
    return packet(f"minecraft:{name}", fields=fields)


SENT_TWO_WAYS = {
    "container_set_slot.state_id": (
        _fields("container_set_slot", SLOT),
        _fields("container_set_slot", {**SLOT, "state_id": 9}),
    ),
    "container_set_content.state_id": (
        _fields("container_set_content", CONTENT),
        _fields("container_set_content", {**CONTENT, "state_id": 9}),
    ),
    "chunk_batch_finished.batch_size": (
        _fields("chunk_batch_finished", {"batch_size": 3}),
        _fields("chunk_batch_finished", {"batch_size": 4}),
    ),
    "status_response members the client never reads": (status(VANILLA), status(PUMPKIN_NIGHTLY)),
}
"""For each kind: what vanilla sends, and another spelling that is network traffic only."""


def _verdict(reference: Packet, candidate: Packet) -> Verdict:
    return compare(transcript(("alice", reference)), transcript(("alice", candidate)), [])


@pytest.mark.parametrize("kind", SENT_TWO_WAYS)
def test_a_network_traffic_difference_adds_no_test_case(kind: str) -> None:
    vanilla, other = SENT_TWO_WAYS[kind]

    differing = _verdict(vanilla, other)

    assert differing.divergences
    assert differing.gameplay == ()
    assert differing.test_cases == _verdict(vanilla, vanilla).test_cases


@pytest.mark.parametrize(
    "fields",
    [{}, {"batch_size": 3}],
    ids=["chunk_batch_start", "chunk_batch_finished"],
)
@pytest.mark.parametrize("left_out_by", ["candidate", "reference"])
def test_a_chunk_batch_marker_only_one_side_sent_adds_no_test_case(
    fields: Mapping[str, object], left_out_by: str
) -> None:
    # Two matched markers name no test case: chunk_batch_start has no fields, and
    # chunk_batch_finished none once batch_size is left out.
    name = "chunk_batch_start" if not fields else "chunk_batch_finished"
    health = ("alice", _fields("set_health", {"health": 20.0}))
    sent = transcript(health, ("alice", _fields(name, fields)))

    sides = (sent, transcript(health)) if left_out_by == "candidate" else (transcript(health), sent)
    verdict = compare(*sides, [])

    assert verdict.divergences
    assert verdict.gameplay == ()
    assert verdict.test_cases == ("set_health.health",)


@pytest.mark.parametrize(
    "fields",
    [{}, {"batch_size": 3}],
    ids=["chunk_batch_start", "chunk_batch_finished"],
)
def test_a_chunk_batch_marker_a_tick_late_scores_as_one_left_out(
    fields: Mapping[str, object],
) -> None:
    # Review A of #341, should-fix 1: a late marker was a gameplay Divergence with a test
    # case, so sending it late scored lower than leaving it out.
    name = "chunk_batch_start" if not fields else "chunk_batch_finished"
    health = ("alice", _fields("set_health", {"health": 20.0}))
    marker = ("alice", _fields(name, fields))
    first, second = f"{TICK_MARK}1", f"{TICK_MARK}2"
    on_time = transcript(OBSERVE_OPEN, health, marker, first, second, OBSERVE_CLOSE)
    late = transcript(OBSERVE_OPEN, health, first, marker, second, OBSERVE_CLOSE)
    gone = transcript(OBSERVE_OPEN, health, first, second, OBSERVE_CLOSE)

    verdict = compare(on_time, late, [])

    assert [d.path for d in verdict.divergences] == [TICK_PATH]
    assert verdict.gameplay == ()
    assert verdict.test_cases == compare(on_time, gone, []).test_cases == ("set_health.health",)
