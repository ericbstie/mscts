"""A tick-exact Group's Self-check matches: redstone stepped tick by tick (#23).

The probe Group (`support.probe.REPEATER_STEPPED`) freezes the world, powers a repeater and
its dust inside a window, and steps 10 ticks. Two Reference Instances of the test's own
play it 20 times each.
"""

from pathlib import Path

import pytest
from support.probe import REPEATER_STEPPED
from support.reference import own_reference

from mscts.compare import Outcome
from mscts.run import run_results

_REPEAT = 20


@pytest.mark.reference
@pytest.mark.asyncio
@pytest.mark.timeout(900)  # two boots, then 20 plays of 10 steps on each side
async def test_a_tick_exact_group_self_checks_20_of_20(cache_dir: Path, tmp_path: Path) -> None:
    with own_reference(cache_dir) as reference:
        result = await run_results(
            [REPEATER_STEPPED],
            reference,
            reference,
            workdir=tmp_path / "selfcheck",
            repeat=_REPEAT,
        )

    verdicts = result.verdicts
    assert len(verdicts) == _REPEAT
    not_matching = [v for v in verdicts if v.outcome is not Outcome.MATCH]
    assert not_matching == [], not_matching
    packets = {case.split(".")[0] for case in verdicts[0].test_cases}
    assert packets & {"block_update", "section_blocks_update"}, packets
