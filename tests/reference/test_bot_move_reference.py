"""Bot movement against a live vanilla 26.3: a walk the server accepts, a jump it refuses.

Boots a Reference of its own, since Control moves the player and the player moves.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest

from mscts.bot import Position
from mscts.group import GroupContext
from mscts.runner import Instance
from mscts.transcript import Transcript

pytestmark = pytest.mark.reference

_TIMEOUT_S = 10.0
START = Position(x=0.5, y=-60.0, z=0.5, yaw=0.0, pitch=0.0)
"""Where Control puts the walker: on the flat world's ground, in chunk (0, 0), which the first
chunk batch holds."""

STEP = 0.2
STEPS = 25  # five blocks along x, staying in chunk (0, 0)


@pytest.mark.timeout(180)  # its own boot and stop, two joins, a command and 27 barriers
@pytest.mark.asyncio
async def test_a_walk_a_tick_at_a_time_is_accepted_and_a_20_block_jump_is_corrected(
    boot_reference: Callable[..., AbstractAsyncContextManager[Instance]],
) -> None:
    transcript = Transcript(group_id="reference/bot-move", server="vanilla")
    async with boot_reference() as reference:
        context = GroupContext(reference.endpoint, transcript, timeout_s=_TIMEOUT_S)
        try:
            walker = await context.bot("walker")
            await walker.join()
            await walker.sync()  # past the join's repeated player_position, if any
            await context.control.run("tp walker 0.5 -60 0.5 0 0")
            await walker.sync()
            arrived = walker.position
            walk_from = len(transcript.events)
            for step in range(1, STEPS + 1):
                await walker.move(START.x + STEP * step, START.y, START.z)
                await walker.sync()  # one move per server tick
            walked = walker.position
            corrections = [
                event.packet
                for event in transcript.events[walk_from:]
                if event.bot == "walker" and event.packet.name == "minecraft:player_position"
            ]
            await walker.move(walked.x, walked.y + 20.0, walked.z)
            correction = await walker.expect("minecraft:player_position", timeout_s=_TIMEOUT_S)
            await walker.sync()
            corrected = walker.position
        finally:
            await context.close()

    assert arrived == START
    assert corrections == []
    assert walked == Position(x=START.x + STEP * STEPS, y=-60.0, z=0.5, yaw=0.0, pitch=0.0)
    # "moved too quickly": back to where the server has the player, absolutely.
    fields = correction.fields or {}
    assert (fields["x"], fields["y"], fields["z"], fields["flags"]) == (walked.x, -60.0, 0.5, 0)
    assert corrected == walked
