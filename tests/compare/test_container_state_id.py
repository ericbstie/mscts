"""`state_id` of a container packet is network traffic only (ADR-0007, #283).

The client stores it in `AbstractContainerMenu.stateId` (`initializeContents`, `setItem`) and
reads it only to copy it into its next `ServerboundContainerClickPacket`
(`MultiPlayerGameMode.handleContainerInput`), so no player sees it.
"""

from collections.abc import Mapping

import pytest

from mscts.compare import Observability, Verdict, compare
from tests.compare.build import packet, transcript

STONE = {"count": 64, "item": 1, "components": {"added": [], "removed": []}}
CONTENT = {"window_id": 0, "state_id": 5, "slot_data": [None, STONE], "carried_item": None}
SLOT = {"window_id": 1, "state_id": 5, "slot": 36, "slot_data": STONE}
PACKETS: Mapping[str, Mapping[str, object]] = {
    "container_set_content": CONTENT,
    "container_set_slot": SLOT,
}


def _compared(
    name: str, reference: Mapping[str, object], candidate: Mapping[str, object]
) -> Verdict:
    sent = [packet(f"minecraft:{name}", fields=fields) for fields in (reference, candidate)]
    return compare(transcript(("alice", sent[0])), transcript(("alice", sent[1])), [])


@pytest.mark.parametrize("name", PACKETS)
def test_another_state_id_is_network_traffic_only(name: str) -> None:
    fields = PACKETS[name]
    verdict = _compared(name, fields, {**fields, "state_id": 9})
    assert [(d.path, d.observability) for d in verdict.divergences] == [
        ("state_id", Observability.NETWORK_TRAFFIC)
    ]
    assert verdict.gameplay == ()
    assert verdict.differing == {f"{name}.state_id": Observability.NETWORK_TRAFFIC}


@pytest.mark.parametrize("name", PACKETS)
def test_the_rest_of_the_packet_is_still_gameplay(name: str) -> None:
    fields = PACKETS[name]
    verdict = _compared(name, fields, {**fields, "state_id": 9, "window_id": 2})
    assert verdict.differing == {
        f"{name}.state_id": Observability.NETWORK_TRAFFIC,
        f"{name}.window_id": Observability.GAMEPLAY,
    }
