"""An Observation window around a Control command makes a gameplay Group's Self-check match.

The probe Group (`support.probe.SETBLOCK_OBSERVED`) joins a Bot, has Control set a block
inside a window, and compares what the Bot sees of it. Two Reference Instances of the
test's own play it 20 times each.
"""

from pathlib import Path

import pytest
from support.probe import SETBLOCK_OBSERVED
from support.reference import own_reference

from mscts.compare import Outcome
from mscts.run import run_results

_REPEAT = 20


@pytest.mark.reference
@pytest.mark.asyncio
@pytest.mark.timeout(600)  # two boots, then 20 plays of two joins and a window on each side
async def test_a_group_that_sets_a_block_inside_a_window_self_checks_20_of_20(
    cache_dir: Path, tmp_path: Path
) -> None:
    with own_reference(cache_dir) as reference:
        result = await run_results(
            [SETBLOCK_OBSERVED],
            reference,
            reference,
            workdir=tmp_path / "selfcheck",
            repeat=_REPEAT,
        )

    verdicts = result.verdicts
    assert len(verdicts) == _REPEAT
    not_matching = [v for v in verdicts if v.outcome is not Outcome.MATCH]
    assert not_matching == [], not_matching
    # Of play, it compared what the command did, and nothing the server sent on a clock,
    # nor anything Control received (its feedback is a system_chat).
    # A test case is `<packet>.<field path>` once the packet decodes, so look at the packets.
    packets = {case.split(".")[0] for case in verdicts[0].test_cases}
    assert "block_update" in packets, packets
    outside = {"set_time", "play:keep_alive", "award_stats", "login", "system_chat"}
    assert not outside & packets, packets
