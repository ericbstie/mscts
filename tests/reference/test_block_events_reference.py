"""Block and world events on a live vanilla 26.3: each packet decodes strictly (#29).

Control sets a block, fills, plays a note block with a redstone block and blows up a TNT near
a Bot, each in an Observation window. Every block and world event packet the watcher gets
decodes into fields and encodes back to the bytes vanilla sent. Boots a Reference of its own,
since the commands change the world.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest
from support.block_events import PACKETS, SCENARIOS, play, undecoded

from mscts.group import GroupContext
from mscts.runner import Instance
from mscts.transcript import Transcript

pytestmark = pytest.mark.reference

_TIMEOUT_S = 10.0


@pytest.mark.timeout(240)  # its own boot and stop, two joins and four windows
@pytest.mark.asyncio
async def test_block_and_world_events_decode_strictly_and_encode_back_byte_for_byte(
    boot_reference: Callable[..., AbstractAsyncContextManager[Instance]],
) -> None:
    transcript = Transcript(group_id="reference/block-events", server="vanilla")
    async with boot_reference() as reference:
        context = GroupContext(reference.endpoint, transcript, timeout_s=_TIMEOUT_S)
        try:
            played = await play(context, transcript)
        finally:
            await context.close()

    assert [one.scenario for one in played] == list(SCENARIOS)
    for one in played:
        assert not one.missing, f"vanilla has no /{one.missing}: {one.scenario.name}"
        assert one.scenario.expects <= one.names, (one.scenario.name, sorted(one.names))
        assert one.names <= PACKETS
    assert not undecoded(played), undecoded(played)
