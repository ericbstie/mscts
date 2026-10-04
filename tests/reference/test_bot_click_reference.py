"""A Bot's clicks against a live vanilla 26.3: a shift-click into a chest and a number key.

Boots a Reference of its own, since Control gives items and places a chest. The Bot predicts
each click as the client does; vanilla checks the prediction against its own click and corrects
only what differs, so a right prediction draws no correction. Reopening the chest then shows
what vanilla holds.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest

from mscts.bot import Face
from mscts.group import GroupContext
from mscts.inventory import Stack
from mscts.runner import Instance
from mscts.transcript import Transcript

pytestmark = pytest.mark.reference

_TIMEOUT_S = 10.0
CLICKER = "clicker"
CHEST = (2, -60, 0)
"""On the flat world's grass, two blocks east of where the clicker stands, in reach."""

SETUP = (
    "tp clicker 0.5 -60 0.5 0 0",
    "give clicker minecraft:stone 64",
    "give clicker minecraft:diamond_sword",
    "setblock 2 -60 0 minecraft:chest",
)
CORRECTIONS = frozenset({"minecraft:container_set_slot", "minecraft:container_set_content"})


@pytest.mark.timeout(180)  # its own boot and stop, a join, four commands and a few barriers
@pytest.mark.asyncio
async def test_a_shift_click_and_a_number_key_match_what_vanilla_does(
    boot_reference: Callable[..., AbstractAsyncContextManager[Instance]],
) -> None:
    transcript = Transcript(group_id="reference/bot-click", server="vanilla")
    async with boot_reference() as reference:
        context = GroupContext(reference.endpoint, transcript, timeout_s=_TIMEOUT_S)
        try:
            clicker = await context.bot(CLICKER)
            await clicker.join()
            for command in SETUP:
                await context.control.run(command)
            await clicker.place(*CHEST, Face.UP)  # the use opens the chest
            await clicker.sync()
            before = len(transcript.events)
            await clicker.click(54, 0, "quick_move")  # the stone, in hotbar slot 0
            moved = clicker.inventory
            await clicker.click(55, 3, "swap")  # the sword, in hotbar slot 1, to slot 3
            swapped = clicker.inventory
            await clicker.sync()
            later = transcript.events[before:]
            answered = [event.packet.name for event in later if event.bot == CLICKER]
            settled = clicker.inventory
            await clicker.close_container()
            await clicker.place(*CHEST, Face.UP)
            await clicker.sync()
            reopened = clicker.inventory
        finally:
            await context.close()

    stone, sword = Stack("minecraft:stone", 64), Stack("minecraft:diamond_sword", 1)
    assert (moved.slots[0], moved.slots[54], moved.carried) == (stone, None, None)
    assert (swapped.slots[55], swapped.slots[57]) == (None, sword)
    assert not CORRECTIONS & set(answered), answered  # vanilla agreed with both predictions
    assert settled == swapped
    # Vanilla's own view, sent whole with the reopened chest, is what the Bot predicted.
    assert reopened.window_id != swapped.window_id
    assert reopened.slots == swapped.slots
    assert reopened.player[:4] == (None, None, None, sword)
