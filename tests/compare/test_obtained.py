"""When a player obtained an advancement criterion is a clock value: no Comparison compares it.

Two fresh vanilla 26.3 Instances sent the same `update_advancements` at a join but for one
value, when the criterion `unlock_right_away` of `recipes/decorations/crafting_table` was
obtained (#30). Whether a criterion was obtained is gameplay, so it is still compared.
"""

import copy
from pathlib import Path
from typing import cast

from mscts.codec.packets import Codec, Direction, Packet, State
from mscts.codec.wire import Writer
from mscts.compare import MASKED, RANDOM_FIELDS, Divergence, Outcome, Verdict, compare
from tests.compare.build import transcript

CODEC = Codec.load("26.3")
CLIENTBOUND = Direction.CLIENTBOUND
NAME = "minecraft:update_advancements"
RECORDED = Path(__file__).resolve().parents[1] / "codec" / "schemas" / "data"
OBTAINED = "minecraft:update_advancements.progress[*].criteria[*].obtained"


def recorded(boot: int) -> Packet:
    payload = (RECORDED / f"vanilla-26.3-boot{boot}-update_advancements.bin").read_bytes()
    packet_id = CODEC.packet_id(State.PLAY, CLIENTBOUND, NAME)
    return CODEC.decode(State.PLAY, CLIENTBOUND, Writer().var_int(packet_id).to_bytes() + payload)


def _with_obtained(obtained: list[list[int | None]]) -> Packet:
    """The first boot's packet, with each advancement's criteria obtained at these times."""
    fields = copy.deepcopy(recorded(1).fields)
    assert fields is not None
    progress = cast("list[dict[str, list[dict[str, object]]]]", fields["progress"])
    for advancement, times in zip(progress, obtained, strict=True):
        for criterion, time in zip(advancement["criteria"], times, strict=True):
            criterion["obtained"] = time
    data = CODEC.encode(State.PLAY, CLIENTBOUND, NAME, fields)
    return CODEC.decode(State.PLAY, CLIENTBOUND, data)


def _verdict(reference: Packet, candidate: Packet) -> Verdict:
    return compare(transcript(("alice", reference)), transcript(("alice", candidate)), [])


def _paths(divergences: tuple[Divergence, ...]) -> list[tuple[str | None, object, object]]:
    return [(d.path, d.reference, d.candidate) for d in divergences]


def test_when_a_criterion_was_obtained_is_a_random_field_with_the_reason() -> None:
    reason = RANDOM_FIELDS[OBTAINED]
    assert "CriterionProgress" in reason
    assert "clock" in reason


def test_two_vanilla_joins_send_the_same_advancements_but_when_they_were_obtained() -> None:
    first, second = recorded(1), recorded(2)
    assert first.payload != second.payload

    verdict = _verdict(first, second)

    assert verdict.outcome is Outcome.MATCH, verdict.divergences
    assert "update_advancements.progress[].criteria[].obtained" not in verdict.test_cases
    assert "update_advancements.progress[].criteria[].criterion" in verdict.test_cases


def test_criteria_obtained_at_other_times_match() -> None:
    reference = _with_obtained([[5, 6], [7]])
    candidate = _with_obtained([[8, 9], [10]])
    assert _paths(_verdict(reference, candidate).divergences) == []


def test_a_criterion_obtained_on_one_side_only_is_a_difference() -> None:
    reference = _with_obtained([[None, 6], [None]])
    candidate = _with_obtained([[None, 6], [7]])
    verdict = _verdict(reference, candidate)
    assert _paths(verdict.divergences) == [("progress[1].criteria[0].obtained", None, MASKED)]
    assert "update_advancements.progress[].criteria[].obtained" in verdict.test_cases
