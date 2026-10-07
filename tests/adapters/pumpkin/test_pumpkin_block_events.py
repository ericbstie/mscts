"""Block and world events against Pumpkin: what arrives, and what does not decode (#29).

The same script as the reference tier (`support.block_events`): Control runs the commands and
a watcher Bot receives their packets. Pumpkin may send these packets differently from vanilla,
so the test asserts only what a player could observe, that each window's packets arrive; what
fails to decode is listed in the failure message and in the research note as evidence, never
asserted away (docs/research/2026-10-01-block-world-events.md).
"""

from pathlib import Path

import pytest
from support.block_events import play, undecoded
from support.reference import booted

from mscts.adapters.pumpkin import PumpkinAdapter
from mscts.group import GroupContext
from mscts.transcript import Transcript

pytestmark = pytest.mark.candidate

_TIMEOUT_S = 10.0


@pytest.mark.asyncio
@pytest.mark.timeout(240)
async def test_pumpkin_sends_the_block_and_world_events_and_its_decoding_is_listed(
    cache_dir: Path, tmp_path: Path
) -> None:
    transcript = Transcript(group_id="candidate/block-events", server="pumpkin")
    async with booted(cache_dir, tmp_path / "pumpkin", adapter=PumpkinAdapter()) as instance:
        context = GroupContext(instance.endpoint, transcript, timeout_s=_TIMEOUT_S)
        try:
            played = await play(context, transcript)
        finally:
            await context.close()

    for one in played:
        print(  # noqa: T201 - the evidence the research note quotes (pytest -s)
            f"{one.scenario.name}: missing={one.missing!r} "
            f"packets={[(p.name, p.decode_error) for p in one.packets]}"
        )
    print(f"undecoded: {undecoded(played)}")  # noqa: T201
    gaps = [
        f"{one.scenario.name}: {sorted(one.scenario.expects - one.names)} did not arrive"
        for one in played
        if not one.scenario.expects <= one.names
    ]
    assert not gaps, gaps
