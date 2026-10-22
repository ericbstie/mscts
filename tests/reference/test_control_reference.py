"""Control on a live vanilla 26.3: a command's feedback, and another Bot seeing what it did.

Boots a Reference of its own, since the command changes the world.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest
from support.block_probe import at_block
from support.control import SETBLOCK

from mscts.group import GroupContext
from mscts.runner import Instance
from mscts.transcript import Transcript

pytestmark = pytest.mark.reference

_TIMEOUT_S = 10.0


@pytest.mark.timeout(180)  # its own boot and stop, two joins and a command
@pytest.mark.asyncio
async def test_control_returns_the_feedback_and_another_bot_sees_the_block(
    boot_reference: Callable[..., AbstractAsyncContextManager[Instance]],
) -> None:
    transcript = Transcript(group_id="reference/control", server="vanilla")
    async with boot_reference() as reference:
        context = GroupContext(reference.endpoint, transcript, timeout_s=_TIMEOUT_S)
        try:
            watcher = await context.bot("watcher")
            await watcher.join()
            said = await context.control.run(SETBLOCK)
            await watcher.expect("minecraft:block_update", timeout_s=_TIMEOUT_S, where=at_block)
        finally:
            await context.close()

    # "Changed the block at 1, -60, 1": the translation key and its arguments, as NBT.
    assert [b"commands.setblock.success" in packet.payload for packet in said] == [True], said
